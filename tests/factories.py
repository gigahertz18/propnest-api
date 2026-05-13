from app.models.property import Property, RentalType, PropertyStatus
import uuid


def make_property(
    name: str = "Test Property",
    address: str = "123 Test Street",
    description: str | None = "A test property",
    rental_type: RentalType = RentalType.long_term,
    listing_platform: str = "direct",
    status: PropertyStatus = PropertyStatus.vacant,
) -> dict:
    """Returns a dict matching PropertyCreate schema."""
    return {
        "name": name,
        "address": address,
        "description": description,
        "rental_type": rental_type.value,
        "listing_platform": listing_platform,
        "status": status.value,
    }


def make_property_model(db, **kwargs) -> Property:
    """Creates and persists a Property directly in the test DB."""
    data = make_property(**kwargs)
    obj = Property(
        id=str(uuid.uuid4()),
        **{k: v for k, v in data.items()},
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
