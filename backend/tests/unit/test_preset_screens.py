from app.services.preset_screens import PRESET_SCREENS, _matches_preset_filters


def _leaders_screen():
    return next(
        screen
        for screen in PRESET_SCREENS
        if screen["id"] == "leaders_in_leading_groups"
    )


def test_leaders_in_leading_groups_preset_filters_for_v1_contract():
    screen = _leaders_screen()

    matching = {
        "symbol": "LEAD",
        "ibd_group_rank": 40,
        "rs_rating": 80,
        "composite_score": 70,
        "volume": 100_000_000,
    }

    assert screen["name"] == "Leaders in Leading Groups"
    assert screen["sort_by"] == "composite_score"
    assert screen["sort_order"] == "desc"
    assert _matches_preset_filters(matching, screen["filters"]) is True
    assert _matches_preset_filters(
        {**matching, "ibd_group_rank": 41},
        screen["filters"],
    ) is False
    assert _matches_preset_filters(
        {**matching, "rs_rating": 79},
        screen["filters"],
    ) is False
    assert _matches_preset_filters(
        {**matching, "composite_score": 69},
        screen["filters"],
    ) is False
    assert _matches_preset_filters(
        {**matching, "volume": 99_999_999},
        screen["filters"],
    ) is False
