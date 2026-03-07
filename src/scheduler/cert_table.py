from scheduler.models import CertLevel

VEHICLE_GROUP_CERTS: dict[str, CertLevel] = {
    # Van groups
    "A.M1": CertLevel.VAN,
    "A.M3": CertLevel.VAN,
    "D.B9": CertLevel.VAN,
    "D.B9A": CertLevel.VAN,
    "E.B17": CertLevel.VAN,
    "V1": CertLevel.VAN,
    "V1A": CertLevel.VAN,
    "V2": CertLevel.VAN,
    "V2A": CertLevel.VAN,
    "V3": CertLevel.VAN,
    "V4": CertLevel.VAN,
    "V4A": CertLevel.VAN,
    "V5": CertLevel.VAN,
    "V5D": CertLevel.VAN,
    "V5TDC": CertLevel.VAN,
    "V75BT": CertLevel.VAN,
    "VH18B": CertLevel.VAN,
    "VH44T": CertLevel.VAN,
    # Truck groups (require C1/SRC)
    "C.F3": CertLevel.VAN_TRUCK,
    "C.F4": CertLevel.VAN_TRUCK,
    "E.A17": CertLevel.VAN_TRUCK,
}


def driver_can_do_group(cert: CertLevel, vehicle_group: str) -> bool:
    required = VEHICLE_GROUP_CERTS.get(vehicle_group)
    if required is None:
        raise ValueError(f"Unknown vehicle group: {vehicle_group}")
    if required == CertLevel.VAN:
        return True
    return cert == CertLevel.VAN_TRUCK
