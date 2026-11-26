"""Great-circle distance and bearing (sphere radius 6371.0 km)."""
import numpy as np


def hav(lat1, lon1, lat2, lon2):
    """Distance in km."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def bearing(lat1, lon1, lat2, lon2):
    """Initial bearing in degrees, clockwise from north, in [0, 360)."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    x = np.sin(lon2 - lon1) * np.cos(lat2)
    y = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(lon2 - lon1)
    return np.degrees(np.arctan2(x, y)) % 360


def sector_of(lat1, lon1, lat2, lon2, n_sectors=8):
    """Compass sector index of the bearing from point 1 to point 2."""
    return (bearing(lat1, lon1, lat2, lon2) / (360.0 / n_sectors)).astype(int) % n_sectors
