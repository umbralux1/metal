"""Яндекс Карты: виджет-iframe без API-ключа и ссылка на маршрут."""

from dataclasses import dataclass
from urllib.parse import urlencode

from app.core.config import settings

# Центр города для карты без точного адреса склада (долгота, широта — порядок Яндекса)
CITY_CENTERS = {"Москва": (37.617635, 55.755814)}
CITY_ZOOM = 10


@dataclass(frozen=True)
class MapView:
    widget_src: str  # адрес для <iframe>
    open_url: str  # карта на yandex.ru
    route_url: str | None  # маршрут до склада; None — точного адреса нет
    has_pin: bool
    lat: float | None = None
    lon: float | None = None


def _coords(lon: float, lat: float) -> str:
    return f"{lon:.6f},{lat:.6f}"


def yandex_map() -> MapView:
    if settings.map_lat is not None and settings.map_lon is not None:
        ll = _coords(settings.map_lon, settings.map_lat)
        params = {"ll": ll, "z": settings.map_zoom, "pt": f"{ll},pm2rdm"}
        open_params = {"ll": ll, "z": settings.map_zoom, "pt": ll}
        route = "https://yandex.ru/maps/?" + urlencode(
            {"rtext": f"~{settings.map_lat},{settings.map_lon}", "rtt": "auto"}
        )
        return MapView(
            widget_src="https://yandex.ru/map-widget/v1/?" + urlencode(params),
            open_url="https://yandex.ru/maps/?" + urlencode(open_params),
            route_url=route,
            has_pin=True,
            lat=settings.map_lat,
            lon=settings.map_lon,
        )
    lon, lat = CITY_CENTERS.get(settings.city, CITY_CENTERS["Москва"])
    params = {"ll": _coords(lon, lat), "z": CITY_ZOOM}
    return MapView(
        widget_src="https://yandex.ru/map-widget/v1/?" + urlencode(params),
        open_url="https://yandex.ru/maps/?" + urlencode(params),
        route_url=None,
        has_pin=False,
    )
