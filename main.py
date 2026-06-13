import datetime
import os
import calendar
import secrets
from collections import defaultdict
from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
import dotenv

import models
from database import engine, get_db

# Load environment variables
dotenv.load_dotenv()

# Initialize SQLite database tables
models.Base.metadata.create_all(bind=engine)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Security / Basic Authentication
security = HTTPBasic()

def get_current_user(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = os.environ.get("APP_USERNAME", "admin")
    correct_password = os.environ.get("APP_PASSWORD", "admin")
    
    is_correct_username = secrets.compare_digest(credentials.username, correct_username)
    is_correct_password = secrets.compare_digest(credentials.password, correct_password)
    
    if not (is_correct_username and is_correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

app = FastAPI(title="fintu")


# Mount static files
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Templates configuration
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Helper: calculate summary statistics for a period
def get_summary_stats(db: Session, filter_type: str = "current_month"):
    today = datetime.date.today()
    query = db.query(models.Transaction)
    
    if filter_type == "7_days":
        start_date = today - datetime.timedelta(days=6)
        query = query.filter(models.Transaction.date >= start_date)
    elif filter_type == "14_days":
        start_date = today - datetime.timedelta(days=13)
        query = query.filter(models.Transaction.date >= start_date)
    elif filter_type == "current_month":
        start_date = datetime.date(today.year, today.month, 1)
        query = query.filter(models.Transaction.date >= start_date)
    # "all_time" has no filter
    
    txs = query.all()
    income = sum(t.amount for t in txs if t.type == 'income')
    expense = sum(t.amount for t in txs if t.type == 'expense')
    balance = income - expense
    return {
        "income": income,
        "expense": expense,
        "balance": balance
    }

# Helper: get transactions grouped by date (limited to current month by default)
def get_grouped_transactions(db: Session, current_month_only: bool = True):
    today = datetime.date.today()
    query = db.query(models.Transaction)
    
    if current_month_only:
        start_date = datetime.date(today.year, today.month, 1)
        query = query.filter(models.Transaction.date >= start_date)
        
    txs = query.all()
    # Sort descending by date, and within the same date, descending by id (newest first)
    sorted_txs = sorted(txs, key=lambda x: (x.date, x.id), reverse=True)
    
    transactions_by_date = defaultdict(list)
    for tx in sorted_txs:
        transactions_by_date[tx.date].append(tx)
        
    return transactions_by_date

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def index(request: Request, db: Session = Depends(get_db)):
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    # By default, show current month's KPIs and list
    summary = get_summary_stats(db, "current_month")
    transactions_by_date = get_grouped_transactions(db, current_month_only=True)
    
    # We pass the transactions list to check empty states for the current month
    start_date = datetime.date(today.year, today.month, 1)
    transactions = db.query(models.Transaction).filter(models.Transaction.date >= start_date).all()
    
    current_date_str = today.strftime("%B %d, %Y")
    
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "active_page": "dashboard",
            "summary": summary,
            "transactions": transactions,
            "transactions_by_date": transactions_by_date,
            "today": today,
            "yesterday": yesterday,
            "current_date": current_date_str,
            "oob": False
        }
    )

@app.get("/summary", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def summary_filter(request: Request, filter: str = "current_month", db: Session = Depends(get_db)):
    summary = get_summary_stats(db, filter)
    return templates.TemplateResponse(
        request=request,
        name="partials/summary.html",
        context={
            "summary": summary,
            "oob": False
        }
    )

@app.post("/transactions", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def create_transaction(
    request: Request,
    type: str = Form(...),
    category: str = Form(...),
    amount: float = Form(...),
    comment: str = Form(None),
    db: Session = Depends(get_db)
):
    # Strip comment and set empty strings to None
    comment_val = comment.strip() if comment else None
    if comment_val == "":
        comment_val = None
        
    # Validation
    if type not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="Invalid transaction type")
        
    # Save transaction
    db_tx = models.Transaction(
        type=type,
        category=category.strip(),
        amount=amount,
        comment=comment_val,
        date=datetime.date.today()  # Defaults to current date as requested
    )
    db.add(db_tx)
    db.commit()
    db.refresh(db_tx)
    
    # Fetch updated data (defaulting to current month)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    summary = get_summary_stats(db, "current_month")
    transactions_by_date = get_grouped_transactions(db, current_month_only=True)
    
    start_date = datetime.date(today.year, today.month, 1)
    transactions = db.query(models.Transaction).filter(models.Transaction.date >= start_date).all()
    
    return templates.TemplateResponse(
        request=request,
        name="partials/post_response.html",
        context={
            "summary": summary,
            "transactions": transactions,
            "transactions_by_date": transactions_by_date,
            "today": today,
            "yesterday": yesterday,
            "oob": True
        }
    )

@app.delete("/transactions/{tx_id}", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def delete_transaction(
    request: Request,
    tx_id: int,
    db: Session = Depends(get_db)
):
    tx = db.query(models.Transaction).filter(models.Transaction.id == tx_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
        
    db.delete(tx)
    db.commit()
    
    # Fetch updated summary statistics (using current month as base)
    summary = get_summary_stats(db, "current_month")
    
    return templates.TemplateResponse(
        request=request,
        name="partials/delete_response.html",
        context={
            "summary": summary,
            "oob": True
        }
    )

@app.get("/history", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def get_history(request: Request, db: Session = Depends(get_db)):
    today = datetime.date.today()
    current_date_str = today.strftime("%B %d, %Y")
    
    # Find months in the last 60 days (current month and previous month)
    # Month 1: Current month
    m1_month = today.month
    m1_year = today.year
    
    # Month 2: Previous month
    if today.month == 1:
        m2_month = 12
        m2_year = today.year - 1
    else:
        m2_month = today.month - 1
        m2_year = today.year
        
    # Query transactions in the last 60 days to place dots on calendar
    start_60_days = today - datetime.timedelta(days=59)
    txs = db.query(models.Transaction).filter(models.Transaction.date >= start_60_days).all()
    
    # Group transactions by type for each date
    tx_types_by_date = defaultdict(set)
    for tx in txs:
        tx_types_by_date[tx.date].add(tx.type)
        
    cal_obj = calendar.Calendar(firstweekday=6) # Sunday start
    
    def get_month_data(year, month):
        weeks = cal_obj.monthdays2calendar(year, month)
        grid = []
        for week in weeks:
            week_days = []
            for day, wd in week:
                if day == 0:
                    week_days.append({"day": 0, "date": None, "in_window": False, "activity": None})
                else:
                    d = datetime.date(year, month, day)
                    in_window = start_60_days <= d <= today
                    
                    # Compute activity dot classes
                    activity = None
                    if in_window:
                        types = tx_types_by_date.get(d, set())
                        if "income" in types and "expense" in types:
                            activity = "both"
                        elif "income" in types:
                            activity = "income"
                        elif "expense" in types:
                            activity = "expense"
                            
                    is_today = (d == today)
                    week_days.append({
                        "day": day,
                        "date": d,
                        "in_window": in_window,
                        "is_today": is_today,
                        "activity": activity
                    })
            grid.append(week_days)
        return {
            "name": calendar.month_name[month],
            "year": year,
            "grid": grid
        }
        
    months = [
        get_month_data(m1_year, m1_month),
        get_month_data(m2_year, m2_month)
    ]
    
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "active_page": "history",
            "months": months,
            "current_date": current_date_str,
            "today": today
        }
    )

@app.get("/history/day", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def get_history_day(request: Request, date: str, db: Session = Depends(get_db)):
    try:
        selected_date = datetime.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
        
    txs = db.query(models.Transaction).filter(models.Transaction.date == selected_date).all()
    
    # Calculate stats for this specific day
    income = sum(t.amount for t in txs if t.type == 'income')
    expense = sum(t.amount for t in txs if t.type == 'expense')
    
    return templates.TemplateResponse(
        request=request,
        name="partials/day_breakdown.html",
        context={
            "selected_date": selected_date,
            "stats": {"income": income, "expense": expense},
            "transactions": txs
        }
    )
