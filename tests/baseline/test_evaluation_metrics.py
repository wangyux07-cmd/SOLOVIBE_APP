from types import SimpleNamespace

from scripts.evaluate_itinerary_live import itinerary_contract, percentile


def test_small_sample_p95_uses_nearest_rank():
    assert percentile([10, 20, 30, 40, 50, 60], 0.95) == 60
    assert percentile([10, 20, 30, 40, 50, 60], 0.5) == 30
    assert percentile([], 0.95) is None


def test_live_report_rejects_a_leg_without_provider_geometry():
    constraints = SimpleNamespace(meal_requirement='dinner', available_minutes=200,
                                  max_walk_minutes=50)
    stops = [{'kind': 'visit'}, {'kind': 'dinner', 'arrival_local': '18:00'}]
    legs = [{'from_coordinate': 'a', 'to_coordinate': 'b', 'route': {
        'provider': 'amap', 'origin_coordinate': 'a', 'destination_coordinate': 'b',
        'distance_meters': 100, 'walking_minutes': 2, 'observed_at': 'now',
        'polyline': ['a', 'b']}} for _ in range(3)]
    itinerary = {'stops': stops, 'legs': legs, 'total_minutes': 120, 'total_walk_minutes': 30}
    assert itinerary_contract(itinerary, constraints)['hard_constraints_pass'] is True
    legs[1]['route']['polyline'] = []
    assert itinerary_contract(itinerary, constraints)['hard_constraints_pass'] is False
