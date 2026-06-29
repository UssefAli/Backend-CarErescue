from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.schemas import SkillName
from dependencies.helper import Status, swagger_responses
from dependencies.permissions import require_admin, require_mechanic, require_user
from app.db.models import  LocationTracking, MechanicSkill, Skill, get_async_session , User ,  ServiceRequest 
from datetime import datetime, timezone


from routes.mechanics import get_mechanic_skills
from services.distance import calculate_score
from services.weights import get_weights




router = APIRouter(
    prefix="/requests",
    tags=["request"]
)


    
@router.get(
    "",
    status_code=200,
    summary="Get all service requests",
    description="""
Retrieve all service requests in the system.

Includes:
- User and mechanic information
- Request status and type
- Creation and completion timestamps

🔒 Authentication required  
🛡 Admin access required
    """,
    responses=swagger_responses(
        success_message={
            "requests": [
                {
                    "id": 1,
                    "user id": "uuid",
                    "user name": "John Doe",
                    "mechanic id": "uuid",
                    "mechanic name": "Ahmed Ali",
                    "status": "Completed",
                    "type": "engine",
                    "created at": "2024-01-01T10:00:00",
                    "completed_at": "2024-01-01T11:00:00",
                }
            ]
        },
        access_role="Admin",
    ),
)
async def get_all_requests(
    admin = Depends(require_admin),
    session : AsyncSession = Depends(get_async_session)
):
    try:
        result = await session.execute(
            select(ServiceRequest).order_by(ServiceRequest.created_at.desc())
        )
        requests = result.scalars().all()
        requests_list = []

        for request in requests:
            result1 = await session.execute(select(User).where(User.id == request.user_id))
            user = result1.scalar_one_or_none()

            result2 = await session.execute(select(User).where(User.id == request.mechanic_id))
            mechanic = result2.scalar_one_or_none()

            if not mechanic:
                mechanic_id = "----"
                mechanic_name = "----"
            else:
                mechanic_id = mechanic.id
                mechanic_name = mechanic.name

            if request.status != "Completed":
                completed_at = "----"
            else:
                completed_at = request.completed_at

            requests_list.append(
                {
                    "id": request.request_id,
                    "user id": request.user_id,
                    "user name": user.name,
                    "mechanic id": mechanic_id,
                    "mechanic name": mechanic_name,
                    "status": request.status,
                    "type": request.request_type,
                    "created at": request.created_at,
                    "completed_at": completed_at,
                }
            )
        return {"requests": requests_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.post(
    "/user/create",
    status_code=200,
    summary="Create service request",
    description="""
Create a new service request for the authenticated user.

📌 Rules:
- User must have location set
- Only one active request is allowed

Initial status will be **Pending**.

🔒 User authentication required
    """,
    responses=swagger_responses(
        success_message={"message": "your request status is Pending"},
        access_role="User",
        bad_request_message="set your location first",
    ),
)
async def create_request(
    request_type : SkillName,
    session: AsyncSession = Depends(get_async_session),
    user : User = Depends(require_user)
):
    try:
        if not user.user_lat or not user.user_lng:
            raise HTTPException(status_code=400, detail="set your location first")

        result = await session.execute(
            select(ServiceRequest).where(
                ServiceRequest.user_id == user.id,
                ServiceRequest.status.in_((Status.accepted, Status.pending))
            )
        )
        request = result.scalar_one_or_none()
        if request:
            raise HTTPException(
                status_code=400,
                detail=f"you already have request {request.status}"
            )

        request = ServiceRequest(
            user_id=user.id,
            request_type=request_type,
            status=Status.pending,
            user_lat=user.user_lat,
            user_lng=user.user_lng,
        )
        session.add(request)
        await session.commit()
        await session.refresh(request)

        return {"message": "your request status is Pending"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))







@router.get(
    "/user/request",
    status_code=200,
    summary="Get current user request",
    description="""
Retrieve the currently active request for the authenticated user.

🔒 User authentication required
    """,
    responses=swagger_responses(
        success_message={
            "current request": {
                "mechanic id": "uuid",
                "mechanic name": "Ahmed Ali",
                "status": "Accepted",
                "type": "engine",
                "created at": "2024-01-01T12:00:00",
            }
        },
        access_role="User",
        not_found=True,
    ),
)
async def get_user_request_details(
    session : AsyncSession = Depends(get_async_session),
    cur_user : User = Depends(require_user),
):
    try:
        result = await session.execute(
            select(ServiceRequest).where(
                ServiceRequest.user_id == cur_user.id,
                ServiceRequest.status.in_((Status.pending, Status.accepted , Status.arrived))
            )
        )
        request = result.scalar_one_or_none()
        if not request:
            raise HTTPException(status_code=404, detail="no request")

        result2 = await session.execute(select(User).where(User.id == request.mechanic_id))
        mechanic = result2.scalar_one_or_none()

        if not mechanic:
            mechanic_id = "----"
            mechanic_name = "----"
        else:
            mechanic_id = mechanic.id
            mechanic_name = mechanic.name

        request_details = {
            "id": request.request_id,
            "mechanic id": mechanic_id,
            "mechanic name": mechanic_name,
            "status": request.status,
            "type": request.request_type,
            "created at": request.created_at,
        }
        return {"current request": request_details}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.patch(
    "/user/cancel",
    status_code=200,
    summary="Cancel user request",
    description="""
Cancel the currently active request.

- Pending → deleted
- Accepted → marked as canceled

🔒 User authentication required
    """,
    responses=swagger_responses(
        success_message={"message": "the request canceled successfully"},
        access_role="User",
        not_found=True,
    ),
)
async def user_cancel_request(
    cur_user : User = Depends(require_user),
    session : AsyncSession = Depends(get_async_session),
):
    try:
        result = await session.execute(
            select(ServiceRequest).where(
                ServiceRequest.user_id == cur_user.id,
                ServiceRequest.status.in_((Status.accepted, Status.pending, Status.arrived))
            )
        )
        request = result.scalar_one_or_none()

        if not request:
            raise HTTPException(
                status_code=404,
                detail="you have no requests to cancel"
            )

        if request.status == Status.accepted:
            request.status = Status.canceled_user
            await session.commit()
            await session.refresh(request)

            cur_user.canceled_count += 1
            await session.commit()
            await session.refresh(cur_user)
        else:
            await session.delete(request)
            await session.commit()

        return {"message": "the request canceled successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))





@router.get(
    "/user/old_requests",
    status_code=200,
    summary="Get user old requests",
    description="""
Retrieve completed or canceled service requests for the authenticated user.

Includes:
- Mechanic information
- Request status
- Creation and completion timestamps

🔒 User authentication required
    """,
    responses=swagger_responses(
        success_message={
            "requests": [
                {
                    "request id": 10,
                    "mechanic id": "uuid",
                    "mechanic name": "Ahmed Ali",
                    "status": "Completed",
                    "type": "engine",
                    "created at": "2024-01-01T10:00:00",
                    "completed at": "2024-01-01T11:00:00",
                }
            ]
        },
        access_role="User",
    ),
)
async def get_user_old_requests(
    cur_user : User = Depends(require_user),
    session : AsyncSession = Depends(get_async_session)
):
    try:
        result = await session.execute(
            select(ServiceRequest)
            .order_by(ServiceRequest.created_at.desc())
            .where(
                ServiceRequest.user_id == cur_user.id,
                ServiceRequest.status.in_(
                    (Status.completed, Status.canceled_user, Status.canceled_mechanic)
                )
            )
        )
        requests = result.scalars().all()
        requests_list = []

        for request in requests:
            result2 = await session.execute(
                select(User).where(User.id == request.mechanic_id)
            )
            mechanic = result2.scalar_one_or_none()

            if not mechanic:
                mechanic_id = "----"
                mechanic_name = "----"
            else:
                mechanic_id = mechanic.id
                mechanic_name = mechanic.name

            if request.status != Status.completed:
                completed_at = "----"
            else:
                completed_at = request.completed_at

            if request.status == Status.canceled_user:
                status = "Canceled by You"
            else:
                status = request.status

            requests_list.append(
                {
                    "request id": request.request_id,
                    "mechanic id": mechanic_id,
                    "mechanic name": mechanic_name,
                    "status": status,
                    "type": request.request_type,
                    "created at": request.created_at,
                    "completed at": completed_at,
                }
            )
        return {"requests": requests_list}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.get(
    "/available_requests",
    status_code=200,
    summary="Get available requests for mechanic",
    description="""
Retrieve all pending service requests available for the authenticated mechanic.

Requests are:
- Filtered by mechanic skills
- Sorted by calculated score (distance + rating)

🔒 Mechanic authentication required
    """,
    responses=swagger_responses(
        success_message={
            "requests": [
                {
                    "request id": 5,
                    "user name": "John Doe",
                    "type": "brakes",
                    "request lat": 30.05,
                    "request lng": 31.22,
                    "distance in km": 2.5,
                    "created at": "2024-01-01T09:00:00",
                }
            ]
        },
        access_role="Mechanic",
        bad_request_message="set your workshop location first",
    ),
)
async def get_all_available_request_for_mechanic(
    cur_mechanic : User = Depends(require_mechanic),
    session : AsyncSession = Depends(get_async_session)
):
    try:
        if not cur_mechanic.workshop_lat or not cur_mechanic.workshop_lng:
            raise HTTPException(status_code=400, detail="set your workshop location first")
        if cur_mechanic.is_available == False:
            raise HTTPException(status_code=400, detail="update your availabilty first")

        weights = await get_weights(session)
        result = await session.execute(
            select(ServiceRequest).where(ServiceRequest.status == Status.pending)
        )

        requests_list = []

        for request in result.scalars().all():
            if request.request_type not in await get_mechanic_skills(
                cur_mechanic.id, session
            ):
                continue

            result1 = await session.execute(
                select(User).where(User.id == request.user_id)
            )
            user = result1.scalar_one_or_none()

            score = calculate_score(
                user_lat=user.user_lat,
                user_lng=user.user_lng,
                mechanic_lat=cur_mechanic.workshop_lat,
                mechanic_lng=cur_mechanic.workshop_lng,
                mechanic_rating=cur_mechanic.avg_rating,
                rating_weight=weights.rating_weight,
                distance_weight=weights.distance_weight,
            )

            requests_list.append(
                {
                    "request id": request.request_id,
                    "user name": user.name,
                    "type": request.request_type,
                    "request lat": request.user_lat,
                    "request lng": request.user_lng,
                    "distance in km": score["distance_km"],
                    "score": score["total_score"],
                    "created at": request.created_at,
                }
            )

        requests_list.sort(key=lambda x: x["score"], reverse=True)

        final_list = []
        for req in requests_list:
            final_list.append(
                {
                    "request id": req["request id"],
                    "user name": req["user name"],
                    "type": req["type"],
                    "request lat": req["request lat"],
                    "request lng": req["request lng"],
                    "distance in km": req["distance in km"],
                    "created at": req["created at"],
                }
            )

        return {"requests": final_list}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))






@router.get(
    "/available_mechanics",
    status_code=200,
    summary="Get available mechanics for user",
    description="""
Retrieve all available mechanics suitable for the user request type.

Mechanics are:
- Filtered by skill
- Sorted by distance and rating score

🔒 User authentication required
    """,
    responses=swagger_responses(
        success_message={
            "Available mechanics": [
                {
                    "mechanic id": "uuid",
                    "workshop name": "SpeedFix Garage",
                    "workshop lat": 30.01,
                    "workshop lng": 31.20,
                    "distance in km": 4.1,
                }
            ]
        },
        access_role="User",
        bad_request_message="set your location first",
    ),
)
async def get_all_available_mechanic_for_user(
    type : SkillName,
    cur_user : User = Depends(require_user),
    session : AsyncSession = Depends(get_async_session)
):
    try:
        if not cur_user.user_lat or not cur_user.user_lng:
            raise HTTPException(status_code=400, detail="set your location first")

        weights = await get_weights(session)
        result = await session.execute(
            select(User).where(User.role == "mechanic", User.is_available == True)
        )

        mechanics_list = []

        for mechanic in result.scalars().all():
            if not mechanic.workshop_lat or not mechanic.workshop_lng:
                continue

            result1 = await session.execute(
                select(MechanicSkill)
                .join(Skill, Skill.skill_id == MechanicSkill.skill_id)
                .where(
                    MechanicSkill.mechanic_id == mechanic.id,
                    Skill.skill_name == type.value,
                )
            )
            if not result1.scalar_one_or_none():
                continue

            score = calculate_score(
                user_lat=cur_user.user_lat,
                user_lng=cur_user.user_lng,
                mechanic_lat=mechanic.workshop_lat,
                mechanic_lng=mechanic.workshop_lng,
                mechanic_rating=mechanic.avg_rating,
                rating_weight=weights.rating_weight,
                distance_weight=weights.distance_weight,
            )
            if score["total_score"] == 0.0:
                continue
            mechanics_list.append(
                {
                    "mechanic id": mechanic.id,
                    "workshop name": mechanic.workshop_name,
                    "workshop lat": mechanic.workshop_lat,
                    "workshop lng": mechanic.workshop_lng,
                    "distance in km": score["distance_km"],
                    "score": score["total_score"],
                }
            )

        mechanics_list.sort(key=lambda x: x["score"], reverse=True)

        return {"Available mechanics": mechanics_list}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))






@router.get(
    "/mechanic",
    status_code=200,
    summary="Get assigned request for mechanic",
    description="""
Retrieve the currently assigned service request for the authenticated mechanic.

🔒 Mechanic authentication required
    """,
    responses=swagger_responses(
        success_message={
            "request": {
                "request id": 7,
                "user id": "uuid",
                "user name": "John Doe",
                "type": "engine",
                "request lat": 30.03,
                "request lng": 31.25,
                "created at": "2024-01-01T10:00:00",
            }
        },
        access_role="Mechanic",
        not_found=True,
    ),
)
async def get_mechanic_assigned_request_details(
    cur_mechanic : User = Depends(require_mechanic),
    session : AsyncSession = Depends(get_async_session),
):
    try:
        result = await session.execute(
            select(ServiceRequest).where(
                ServiceRequest.mechanic_id == cur_mechanic.id,
                ServiceRequest.status.in_([Status.accepted, Status.arrived]),
            )
        )
        request = result.scalar_one_or_none()

        if not request:
            raise HTTPException(status_code=404, detail="no assigned request")

        result2 = await session.execute(
            select(User).where(User.id == request.user_id)
        )
        user = result2.scalar_one_or_none()

        request_details = {
            "request id": request.request_id,
            "user id": user.id,
            "user name": user.name,
            "type": request.request_type,
            "request lat": request.user_lat,
            "request lng": request.user_lng,
            "created at": request.created_at,
        }
        return {"request": request_details}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.get(
    "/mechanic/old_requests",
    status_code=200,
    summary="Get mechanic old requests",
    description="""
Retrieve completed or canceled service requests for the authenticated mechanic.

This endpoint returns the mechanic's request history, including:
- Requests completed successfully
- Requests canceled by the user
- Requests canceled by the mechanic

📌 **Notes for frontend**
- If the request was not completed, `completed at` will be `"----"`
- If the mechanic canceled the request, status will be `"Canceled by You"`

🔒 **Authentication required**  
🧰 **Mechanic access only**
    """,
    responses=swagger_responses(
        success_message={
            "requests": [
                {
                    "request id": 42,
                    "user id": "9f1c2a8b-6e5a-4c91-bf1a-9e3b7f6a1234",
                    "user name": "Mohamed Ali",
                    "status": "Completed",
                    "type": "engine",
                    "created at": "2024-01-05T14:30:00",
                    "completed at": "2024-01-05T15:45:00"
                },
                {
                    "request id": 41,
                    "user id": "b12a9c77-1c3f-4d91-9a11-7d9b3e8f4567",
                    "user name": "Sara Ibrahim",
                    "status": "Canceled by You",
                    "type": "tires",
                    "created at": "2024-01-03T11:00:00",
                    "completed at": "----"
                }
            ]
        },
        access_role="Mechanic",
        not_found=False,
    ),
)
async def get_mechanic_old_requests(
    cur_mechanic: User = Depends(require_mechanic),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        result = await session.execute(
            select(ServiceRequest)
            .where(
                ServiceRequest.mechanic_id == cur_mechanic.id,
                ServiceRequest.status.in_(
                    (
                        Status.completed,
                        Status.canceled_user,
                        Status.canceled_mechanic,
                    )
                ),
            )
            .order_by(ServiceRequest.created_at.desc())
        )

        requests = result.scalars().all()
        requests_list = []

        for request in requests:
            result = await session.execute(
                select(User).where(User.id == request.user_id)
            )
            user = result.scalar_one_or_none()

            if request.status != Status.completed:
                completed_at = "----"
            else:
                completed_at = request.completed_at

            if request.status == Status.canceled_mechanic:
                status = "Canceled by You"
            else:
                status = request.status

            requests_list.append(
                {
                    "request id": request.request_id,
                    "user id": user.id,
                    "user name": user.name,
                    "status": status,
                    "type": request.request_type,
                    "created at": request.created_at,
                    "completed at": completed_at,
                }
            )

        return {"requests": requests_list}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.patch(
    "/mechanic/cancel",
    status_code=200,
    summary="Cancel assigned request",
    description="""
Cancel the currently assigned request as a mechanic.

🔒 Mechanic authentication required
    """,
    responses=swagger_responses(
        success_message={"message": "the request canceled succefully"},
        access_role="Mechanic",
        not_found=True,
    ),
)
async def mechanic_cancel_request(
    cur_mechanic : User = Depends(require_mechanic),
    session : AsyncSession = Depends(get_async_session),
):
    try:
        result = await session.execute(
            select(ServiceRequest).where(
                ServiceRequest.mechanic_id == cur_mechanic.id,
                ServiceRequest.status.in_([Status.accepted, Status.arrived])
            )
        )
        request = result.scalar_one_or_none()

        if not request:
            raise HTTPException(
                status_code=404,
                detail="you have no assigned requests to cancel",
            )

        request.status = Status.canceled_mechanic
        await session.commit()
        await session.refresh(request)

        cur_mechanic.canceled_count += 1
        await session.commit()
        await session.refresh(cur_mechanic)

        return {"message": "the request canceled succefully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.patch(
    "/mechanic/complete",
    status_code=200,
    summary="Complete assigned request",
    description="""
Mark the currently assigned request as completed.

Updates:
- Request status
- Completion timestamp
- Mechanic job counter

🔒 Mechanic authentication required
    """,
    responses=swagger_responses(
        success_message={"message": "the request completed successfully"},
        access_role="Mechanic",
        not_found=True,
    ),
)
async def mechanic_complete_request(
    cur_mechanic : User = Depends(require_mechanic),
    session : AsyncSession = Depends(get_async_session),
):
    try:
        result = await session.execute(
            select(ServiceRequest).where(
                ServiceRequest.mechanic_id == cur_mechanic.id,
                ServiceRequest.status == Status.arrived,
            )
        )
        request = result.scalar_one_or_none()

        if not request:
            raise HTTPException(
                status_code=404,
                detail="you have no assigned request to complete",
            )

        request.status = Status.completed
        request.completed_at = datetime.now()
        await session.commit()
        await session.refresh(request)

        cur_mechanic.total_jobs += 1
        await session.commit()
        await session.refresh(cur_mechanic)

        return {"message": "the request completed successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))






@router.patch(
    "/mechanic/{request_id}/accept",
    status_code=200,
    summary="Accept service request",
    description="""
Accept a pending service request as a mechanic.

📌 A mechanic can only accept **one request at a time**.

🔒 Mechanic authentication required
    """,
    responses=swagger_responses(
        success_message={"message": "the request accepted succefully"},
        access_role="Mechanic",
        bad_request_message="you can't assign for more than request",
        validation=True
    ),
)
async def mechanic_accept_request(
    request_id : int,
    cur_mechanic : User = Depends(require_mechanic),
    session : AsyncSession = Depends(get_async_session),
):
    try:
        result1 = await session.execute(
            select(ServiceRequest).where(
                ServiceRequest.mechanic_id == cur_mechanic.id,
                ServiceRequest.status == Status.accepted,
            )
        )
        if result1.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="you can't assign for more than request",
            )

        result2 = await session.execute(
            select(ServiceRequest).where(
                ServiceRequest.request_id == request_id
            )
        )
        request = result2.scalar_one_or_none()

        if not request or request.status != Status.pending:
            raise HTTPException(
                status_code=404,
                detail="the request no longer available",
            )

        request.status = Status.accepted
        request.mechanic_id = cur_mechanic.id
        await session.commit()
        await session.refresh(request)

        tracking = LocationTracking(
            request_id = request.request_id,
            mechanic_lat = cur_mechanic.workshop_lat,
            mechanic_lng = cur_mechanic.workshop_lng,
            timestamp = datetime.now(timezone.utc)
        )
        session.add(tracking)
        await session.commit()
        await session.refresh(tracking)

        return {"message": "the request accepted succefully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



