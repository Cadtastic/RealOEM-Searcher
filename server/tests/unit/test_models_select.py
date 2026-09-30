from realoem_mcp.models.select import (
    LEVEL_PARAMS,
    LEVELS,
    SelectLevel,
    SelectOption,
    SelectPage,
)


def _level(name: str, *values: str, selected: str | None = None) -> SelectLevel:
    options = [SelectOption(value=v, label=v.title(), selected=v == selected) for v in values]
    return SelectLevel(level=name, label=name.title(), options=options)


def test_levels_are_in_cascade_order_and_catalog_is_sent_as_archive() -> None:
    assert LEVELS == (
        "product",
        "catalog",
        "series",
        "body",
        "model",
        "market",
        "prod",
        "engine",
        "steering",
        "trans",
    )
    assert LEVEL_PARAMS["catalog"] == "archive"
    assert all(LEVEL_PARAMS[level] == level for level in LEVELS if level != "catalog")


def test_selected_option_is_the_selected_row_or_none() -> None:
    assert _level("body", "Lim", "Cab", selected="Cab").selected_option == SelectOption(
        value="Cab", label="Cab", selected=True
    )
    assert _level("model", "320i", "325i").selected_option is None


def test_select_page_looks_up_levels_by_name() -> None:
    page = SelectPage(
        levels=[_level("product", "P", "M", selected="P"), _level("model", "320i", "325i")],
        vehicle_id=None,
        type_code=None,
        summary=None,
    )
    assert page.level("model") is page.levels[1]
    assert page.level("engine") is None
    assert page.selected("product").value == "P"
    assert page.selected("model") is None
    assert page.selected("engine") is None


def test_select_page_serializes_without_helper_properties() -> None:
    page = SelectPage(
        levels=[_level("product", "P", selected="P")],
        vehicle_id="WL13-USA-07-2008-E93-BMW-328i",
        type_code="WL13",
        summary="3 Series E93 BMW 328i",
    )
    assert page.model_dump() == {
        "levels": [
            {
                "level": "product",
                "label": "Product",
                "options": [{"value": "P", "label": "P", "selected": True}],
            }
        ],
        "vehicle_id": "WL13-USA-07-2008-E93-BMW-328i",
        "type_code": "WL13",
        "summary": "3 Series E93 BMW 328i",
    }
