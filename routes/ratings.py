from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Rating, ServiceRequest, User, get_async_session
from app.db.schemas import RatingCreate
from dependencies.helper import Status, swagger_responses
from dependencies.permissions import require_admin, require_user
from services.weights import update_weights
from datetime import datetime

router = APIRouter(
    prefix = "/ratings",
    tags= ["ratings"]
)




@router.get(
    "/user",
    status_code=200,
    summary="Get current user ratings",
    description="""
Retrieve all ratings submitted by the authenticated user.

🔒 **User authentication required**
    """,
    responses=swagger_responses(
        success_message={
            "ratings": [
                {
                    "rating id": 3,
                    "request id": 77,
                    "mechanic id": "uuid",
                    "mechanic name": "Ahmed Hassan",
                    "rate": 4,
                    "feedback": "Good service",
                    "created at": "2024-01-11T15:40:00"
                }
            ]
        },
        access_role="User",
    ),
)
async def get_all_user_ratings(
    session: AsyncSession = Depends(get_async_session),
    cur_user: User = Depends(require_user),
):
    try:
        result = await session.execute(
            select(Rating)
            .order_by(Rating.created_at.desc())
            .where(Rating.user_id == cur_user.id)
        )
        ratings = result.scalars().all()
        rating_list = []

        for rating in ratings:
            result2 = await session.execute(select(User).where(User.id == rating.mechanic_id))
            mechanic = result2.scalar_one_or_none()
            rating_list.append({
                "rating id": rating.rating_id,
                "request id": rating.request_id,
                "mechanic id": rating.mechanic_id,
                "mechanic name": mechanic.name,
                "rate": rating.rating,
                "feedback": rating.feedback_text,
                "created at": rating.created_at
            })
        return {"ratings": rating_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.post(
    "/create/{request_id}",
    status_code=200,
    summary="Submit a rating",
    description="""
Submit a rating for a completed or canceled request.

🔒 **User authentication required**
    """,
    responses=swagger_responses(
        success_message={"message": "the rate submitted successfully"},
        access_role="User",
        bad_request_message="you've already rated this mechanic",
        not_found=True,
        validation=True
    ),
)
async def submit_rating(
    request_id: int,
    rate_num: int,
    feedback: str,
    session: AsyncSession = Depends(get_async_session),
    cur_user: User = Depends(require_user),
):
    try:
        result2 = await session.execute(select(ServiceRequest).where(ServiceRequest.request_id == request_id))
        request = result2.scalar_one_or_none()

        if not request or request.user_id != cur_user.id:
            raise HTTPException(status_code=404, detail="Request not found")
        if request.status not in (Status.completed, Status.canceled_mechanic):
            raise HTTPException(
                status_code=400,
                detail=f"you can't rate the mechanic because the status is {request.status}"
            )

        result = await session.execute(select(Rating).where(Rating.request_id == request_id))
        rate = result.scalar_one_or_none()
        if rate:
            raise HTTPException(status_code=400, detail="you've already rated this mechanic")

        applied_reward = rate_num / 5

        rating = Rating(
            request_id=request.request_id,
            rating=rate_num,
            feedback_text=feedback,
            user_id=cur_user.id,
            mechanic_id=request.mechanic_id,
            applied_reward=applied_reward
        )

        delta = rating.applied_reward
        await update_weights(session, delta)
        session.add(rating)
        await session.commit()
        await session.refresh(rating)

        result1 = await session.execute(select(Rating).where(Rating.mechanic_id == rating.mechanic_id))
        ratings = result1.scalars().all()

        total_rating_score = 0
        count = 0
        for rate in ratings:
            total_rating_score += rate.rating
            count += 1

        avg_rating = total_rating_score / count
        review_count = count

        result3 = await session.execute(select(User).where(User.id == rating.mechanic_id))
        mechanic = result3.scalar_one_or_none()
        mechanic.avg_rating = avg_rating
        mechanic.review_count = review_count

        await session.commit()
        await session.refresh(mechanic)

        return {"message": "the rate submitted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.patch(
    "/user/{rating_id}",
    status_code=200,
    summary="Modify user rating",
    description="Update an existing rating submitted by the user.",
    responses=swagger_responses(
        success_message={"message": "rate updated successfully"},
        access_role="User",
        not_found=True,
        validation=True
    ),
)
async def modify_user_rating(
    rating_id: int,
    rate_num: int,
    feedback: str,
    session: AsyncSession = Depends(get_async_session),
    cur_user: User = Depends(require_user),
):
    try:
        result = await session.execute(select(Rating).where(Rating.rating_id == rating_id))
        rate = result.scalar_one_or_none()
        if not rate or rate.user_id != cur_user.id:
            raise HTTPException(status_code=404, detail="Rating not found")

        rate.rating = rate_num
        rate.feedback_text = feedback
        rate.created_at = datetime.now()

        new_reward = rate.rating / 5
        old_reward = rate.applied_reward or 0.0
        delta = new_reward - old_reward

        await update_weights(session, delta)
        rate.applied_reward = new_reward
        await session.commit()
        await session.refresh(rate)

        result1 = await session.execute(select(Rating).where(Rating.mechanic_id == rate.mechanic_id))
        ratings = result1.scalars().all()

        total_rating_score = 0
        count = 0
        for rate in ratings:
            total_rating_score += rate.rating
            count += 1

        avg_rating = total_rating_score / count
        result2 = await session.execute(select(User).where(User.id == rate.mechanic_id))
        mechanic = result2.scalar_one_or_none()
        mechanic.avg_rating = avg_rating

        await session.commit()
        await session.refresh(mechanic)

        return {"message": "rate updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.delete(
    "/user/{rating_id}",
    status_code=200,
    summary="Delete user rating",
    description="Delete a rating submitted by the authenticated user.",
    responses=swagger_responses(
        success_message={"message": "rating deleted successfully"},
        access_role="User",
        bad_request_message="Rating not found",
        validation=True
    ),
)
async def delete_user_rating(
    rating_id: int,
    session: AsyncSession = Depends(get_async_session),
    cur_user: User = Depends(require_user),
):
    try:
        result = await session.execute(select(Rating).where(Rating.rating_id == rating_id))
        rate = result.scalar_one_or_none()
        if not rate or rate.user_id != cur_user.id:
            raise HTTPException(status_code=400, detail="Rating not found")

        delta = -rate.applied_reward
        await update_weights(session, delta)

        await session.delete(rate)
        await session.commit()

        result1 = await session.execute(select(User).where(User.id == rate.mechanic_id))
        mechanic = result1.scalar_one_or_none()
        mechanic.review_count -= 1

        result1 = await session.execute(select(Rating).where(Rating.mechanic_id == rate.mechanic_id))
        ratings = result1.scalars().all()

        total_rating_score = 0
        count = 0
        for rate in ratings:
            total_rating_score += rate.rating
            count += 1

        avg_rating = total_rating_score / count
        result2 = await session.execute(select(User).where(User.id == rate.mechanic_id))
        mechanic = result2.scalar_one_or_none()
        mechanic.avg_rating = avg_rating
        mechanic.review_count -= 1

        await session.commit()
        await session.refresh(mechanic)

        return {"messgae": "rating deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
   