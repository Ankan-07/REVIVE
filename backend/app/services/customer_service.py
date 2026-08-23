from typing import Optional, List
from sqlalchemy.orm import Session
from app.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerRead
from app.domain.ids import generate_id


def create_customer(db: Session, data: CustomerCreate) -> CustomerRead:
    customer_id = generate_id("CUS", db)
    db_obj = Customer(
        id=customer_id,
        name=data.name,
        email=data.email,
        phone=data.phone,
        segment=data.segment,
        ltv_amount=data.ltv_amount,
        risk_score=data.risk_score,
    )
    db.add(db_obj)
    db.commit()
    db.refresh(db_obj)
    return CustomerRead.model_validate(db_obj)


def get_customer(db: Session, customer_id: str) -> Optional[CustomerRead]:
    db_obj = db.query(Customer).filter(Customer.id == customer_id).first()
    if not db_obj:
        return None
    return CustomerRead.model_validate(db_obj)


def list_customers(db: Session, skip: int = 0, limit: int = 100) -> List[CustomerRead]:
    items = db.query(Customer).offset(skip).limit(limit).all()
    return [CustomerRead.model_validate(item) for item in items]
