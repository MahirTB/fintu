import datetime
from sqlalchemy import Column, Integer, String, Float, Date
from database import Base

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)  # 'income' or 'expense'
    category = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    comment = Column(String, nullable=True)
    date = Column(Date, default=datetime.date.today, nullable=False)
