import math

# -----------------------
# Distance
# -----------------------
def haversine_distance(lat1, lon1, lat2, lon2 , km = True):
    if km:
        R = 6371.0
    else:
        R = 6371000
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + \
        math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    if km:
        return round(R * c, 2)
    else:
        return R * c


# -----------------------
# Scores
# -----------------------
def normalize_distance(distance_km, max_distance_km=50):
    if distance_km >= max_distance_km:
        return 0.0
    return round(1 - (distance_km / max_distance_km), 4)


def normalize_rating(avg_rating):
    # rating from 1 → 5
    return round((avg_rating - 1) / 4, 4)


# -----------------------
# Final score
# -----------------------
def calculate_score(
    user_lat,
    user_lng,
    mechanic_lat,
    mechanic_lng,
    mechanic_rating,
    max_distance_km=50,
    rating_weight=0.6,
    distance_weight=0.4,
):
    distance_km = haversine_distance(
        user_lat, user_lng, mechanic_lat, mechanic_lng
    )
    if distance_km > max_distance_km:
        return {
            "distance_km": distance_km,
            "distance_score": 0.0,
            "rating_score": 0.0,
            "total_score": 0.0,
        }
    distance_score = normalize_distance(distance_km, max_distance_km)
    rating_score = normalize_rating(mechanic_rating)

    total_score = (
        rating_weight * rating_score +
        distance_weight * distance_score
    )

    return {
        "distance_km": distance_km,
        "distance_score": distance_score,
        "rating_score": rating_score,
        "total_score": round(total_score, 4),
    }
