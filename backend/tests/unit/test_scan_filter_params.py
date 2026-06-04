from inspect import signature

from app.api.v1.scan_filter_params import parse_scan_filters


def test_parse_scan_filters_maps_ibd_group_rank_range():
    kwargs = {name: None for name in signature(parse_scan_filters).parameters}
    filters = parse_scan_filters(
        **{
            **kwargs,
            "min_ibd_group_rank": 1,
            "max_ibd_group_rank": 40,
        }
    )

    rank_filter = next(
        item for item in filters.range_filters if item.field == "ibd_group_rank"
    )
    assert rank_filter.min_value == 1
    assert rank_filter.max_value == 40
