import datetime
import os
import calendar
import secrets
from collections import defaultdict
from fastapi import FastAPI, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
import dotenv

import models
from database import engine, get_db

# Load environment variables
dotenv.load_dotenv()

# Initialize database tables safely
try:
    models.Base.metadata.create_all(bind=engine)
except Exception as e:
    print(f"Warning: could not create database tables on startup: {e}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Security / Session Cookie Authentication
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import RedirectResponse

class RedirectException(Exception):
    def __init__(self, url: str):
        self.url = url

def get_current_user(request: Request):
    user = request.session.get("user")
    if not user:
        raise RedirectException("/login")
    return user

app = FastAPI(title="fintu")

# Global Exception Handler to capture unhandled runtime errors
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return HTMLResponse(
        status_code=500,
        content=f"<html><body style='font-family:monospace;padding:2rem;background:#111;color:#f87171;'>"
                f"<h2>Application Error</h2>"
                f"<pre style='background:#1e1e1e;padding:1rem;border-radius:6px;overflow-x:auto;color:#e5e7eb;'>"
                f"{traceback.format_exc()}</pre></body></html>"
    )

# Register Exception Handler for Redirects
@app.exception_handler(RedirectException)
def redirect_exception_handler(request: Request, exc: RedirectException):
    if request.headers.get("HX-Request"):
        return HTMLResponse(status_code=200, headers={"HX-Redirect": exc.url})
    return RedirectResponse(url=exc.url, status_code=status.HTTP_303_SEE_OTHER)

# Register Session Middleware
session_secret = os.environ.get("SESSION_SECRET_KEY", "fintu-super-secret-key-change-in-prod")
app.add_middleware(SessionMiddleware, secret_key=session_secret, max_age=86400 * 30) # 30 days session

# Mount static files safely
static_dir = os.path.join(BASE_DIR, "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Templates configuration
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Helper: format comparative trend metrics
def format_trend(curr: float, prev: float, is_expense: bool = False):
    diff = curr - prev
    has_prior = (prev != 0)
    
    if prev > 0:
        pct = (diff / prev) * 100
    elif prev < 0 and not is_expense:
        pct = (diff / abs(prev)) * 100
    elif prev == 0 and curr != 0:
        pct = 100.0
    else:
        pct = None
        
    if pct is not None:
        formatted_pct = f"{int(round(abs(pct)))}%"
    else:
        formatted_pct = None
        
    if diff != 0:
        formatted_diff = f"৳{int(round(abs(diff))):,}"
    else:
        formatted_diff = "৳0"
        
    if is_expense:
        # Spending less is positive (green), spending more is negative (red)
        if diff > 0:
            status = "negative"
        elif diff < 0:
            status = "positive"
        else:
            status = "neutral"
    else:
        # Income/Balance: higher is positive (green), lower is negative (red)
        if diff > 0:
            status = "positive"
        elif diff < 0:
            status = "negative"
        else:
            status = "neutral"
            
    is_arrow_up = diff > 0
    is_arrow_down = diff < 0
    show_trend = (curr != 0 or prev != 0)
    
    return {
        "diff": diff,
        "pct": pct,
        "formatted_diff": formatted_diff,
        "formatted_pct": formatted_pct,
        "status": status,
        "is_arrow_up": is_arrow_up,
        "is_arrow_down": is_arrow_down,
        "has_prior": has_prior,
        "show_trend": show_trend
    }

# Helper: calculate date ranges and labels for period filters
def get_period_dates(filter_type: str = "current_month"):
    today = datetime.date.today()
    if filter_type == "current_month":
        curr_start = datetime.date(today.year, today.month, 1)
        curr_end = None
        period_label = "vs last month"
        display_name = "This Month"
        
        # Calculate full previous month date window
        if today.month == 1:
            prev_year = today.year - 1
            prev_month = 12
        else:
            prev_year = today.year
            prev_month = today.month - 1
            
        prev_start = datetime.date(prev_year, prev_month, 1)
        last_day = calendar.monthrange(prev_year, prev_month)[1]
        prev_end = datetime.date(prev_year, prev_month, last_day)
        has_comparison = True
        
    elif filter_type == "7_days":
        curr_start = today - datetime.timedelta(days=6)
        curr_end = None
        period_label = "vs prev 7 days"
        display_name = "Last 7 Days"
        
        prev_start = today - datetime.timedelta(days=13)
        prev_end = today - datetime.timedelta(days=7)
        has_comparison = True
        
    elif filter_type == "14_days":
        curr_start = today - datetime.timedelta(days=13)
        curr_end = None
        period_label = "vs prev 14 days"
        display_name = "Last 14 Days"
        
        prev_start = today - datetime.timedelta(days=27)
        prev_end = today - datetime.timedelta(days=14)
        has_comparison = True
        
    else:  # "all_time"
        curr_start = None
        curr_end = None
        prev_start = None
        prev_end = None
        has_comparison = False
        period_label = None
        display_name = "All Time"
        
    return {
        "curr_start": curr_start,
        "curr_end": curr_end,
        "prev_start": prev_start,
        "prev_end": prev_end,
        "has_comparison": has_comparison,
        "period_label": period_label,
        "display_name": display_name
    }

# Helper: calculate category breakdown metrics
def get_category_breakdown(txs: list, filter_type: str = "current_month", custom_days: int = None):
    today = datetime.date.today()
    expense_txs = [t for t in txs if t.type == 'expense']
    total_expense = sum(t.amount for t in expense_txs)
    
    # Calculate daily average spend for the selected window
    if total_expense <= 0:
        daily_avg_str = "৳0/day"
    else:
        if custom_days is not None:
            days = max(1, custom_days)
        elif filter_type == "current_month":
            days = max(1, today.day)
        elif filter_type == "7_days":
            days = 7
        elif filter_type == "14_days":
            days = 14
        else:  # "all_time"
            dates = [t.date for t in txs if t.type == 'expense']
            if dates:
                min_date = min(dates)
                days = max(1, (today - min_date).days + 1)
            else:
                days = 1
        avg = round(total_expense / days)
        daily_avg_str = f"৳{int(avg):,}/day"
            
    expense_by_cat = defaultdict(float)
    expense_count_by_cat = defaultdict(int)
    for t in expense_txs:
        expense_by_cat[t.category] += t.amount
        expense_count_by_cat[t.category] += 1
        
    categories = []
    for cat, amount in sorted(expense_by_cat.items(), key=lambda x: x[1], reverse=True):
        pct = (amount / total_expense * 100) if total_expense > 0 else 0
        pct_str = f"{int(round(pct))}%"
        categories.append({
            "category": cat,
            "amount": amount,
            "formatted_amount": f"৳{int(round(amount)):,}",
            "percentage": pct,
            "formatted_percentage": pct_str,
            "count": expense_count_by_cat[cat]
        })
        
    return {
        "total": total_expense,
        "formatted_total": f"৳{int(round(total_expense)):,}",
        "count": len(expense_txs),
        "daily_avg_str": daily_avg_str,
        "categories": categories
    }

# Helper: calculate summary statistics for a period with previous period comparison
def get_summary_stats(db: Session, filter_type: str = "current_month"):
    period = get_period_dates(filter_type)
    curr_query = db.query(models.Transaction)
    prev_query = db.query(models.Transaction)
    
    if period["curr_start"]:
        curr_query = curr_query.filter(models.Transaction.date >= period["curr_start"])
    if period["curr_end"]:
        curr_query = curr_query.filter(models.Transaction.date <= period["curr_end"])
        
    if period["has_comparison"]:
        if period["prev_start"]:
            prev_query = prev_query.filter(models.Transaction.date >= period["prev_start"])
        if period["prev_end"]:
            prev_query = prev_query.filter(models.Transaction.date <= period["prev_end"])
            
    curr_txs = curr_query.all()
    curr_income = sum(t.amount for t in curr_txs if t.type == 'income')
    curr_expense = sum(t.amount for t in curr_txs if t.type == 'expense')
    curr_balance = curr_income - curr_expense
    
    if period["has_comparison"]:
        prev_txs = prev_query.all()
        prev_income = sum(t.amount for t in prev_txs if t.type == 'income')
        prev_expense = sum(t.amount for t in prev_txs if t.type == 'expense')
        prev_balance = prev_income - prev_expense
        
        comparison = {
            "has_comparison": True,
            "period_label": period["period_label"],
            "balance": format_trend(curr_balance, prev_balance, is_expense=False),
            "income": format_trend(curr_income, prev_income, is_expense=False),
            "expense": format_trend(curr_expense, prev_expense, is_expense=True),
        }
    else:
        comparison = {
            "has_comparison": False,
            "period_label": None,
            "balance": None,
            "income": None,
            "expense": None
        }
        
    savings_rate_str = None
    if curr_income > 0:
        if curr_balance > 0:
            rate = round((curr_balance / curr_income) * 100)
            savings_rate_str = f"{int(rate)}%"
        else:
            savings_rate_str = "0%"
        
    return {
        "income": curr_income,
        "expense": curr_expense,
        "balance": curr_balance,
        "savings_rate_str": savings_rate_str,
        "comparison": comparison,
        "period": period
    }

# Helper: get filtered transactions and grouped by date
def get_filtered_transactions(db: Session, filter_type: str = "current_month"):
    period = get_period_dates(filter_type)
    query = db.query(models.Transaction)
    
    if period["curr_start"]:
        query = query.filter(models.Transaction.date >= period["curr_start"])
    if period["curr_end"]:
        query = query.filter(models.Transaction.date <= period["curr_end"])
        
    txs = query.all()
    sorted_txs = sorted(txs, key=lambda x: (x.date, x.id), reverse=True)
    
    transactions_by_date = defaultdict(list)
    for tx in sorted_txs:
        transactions_by_date[tx.date].append(tx)
        
    return sorted_txs, transactions_by_date

# Helper: get transactions grouped by date (legacy compatibility)
def get_grouped_transactions(db: Session, current_month_only: bool = True):
    filter_type = "current_month" if current_month_only else "all_time"
    _, transactions_by_date = get_filtered_transactions(db, filter_type)
    return transactions_by_date

@app.get("/", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def index(request: Request, db: Session = Depends(get_db)):
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    # By default, show current month's KPIs, breakdown, and list
    summary = get_summary_stats(db, "current_month")
    transactions, transactions_by_date = get_filtered_transactions(db, "current_month")
    breakdown = get_category_breakdown(transactions, "current_month")
    
    current_date_str = today.strftime("%B %d, %Y")
    
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "active_page": "dashboard",
            "summary": summary,
            "breakdown": breakdown,
            "period": summary["period"],
            "transactions": transactions,
            "transactions_by_date": transactions_by_date,
            "today": today,
            "yesterday": yesterday,
            "current_date": current_date_str,
            "oob_summary": False,
            "oob_breakdown": False,
            "oob_tx_list": False
        }
    )

@app.get("/summary", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def summary_filter(request: Request, filter: str = "current_month", db: Session = Depends(get_db)):
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    summary = get_summary_stats(db, filter)
    transactions, transactions_by_date = get_filtered_transactions(db, filter)
    breakdown = get_category_breakdown(transactions, filter)
    
    return templates.TemplateResponse(
        request=request,
        name="partials/filter_response.html",
        context={
            "summary": summary,
            "breakdown": breakdown,
            "period": summary["period"],
            "transactions": transactions,
            "transactions_by_date": transactions_by_date,
            "today": today,
            "yesterday": yesterday,
            "oob_summary": False,
            "oob_breakdown": True,
            "oob_tx_list": True
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
    transactions, transactions_by_date = get_filtered_transactions(db, "current_month")
    breakdown = get_category_breakdown(transactions, "current_month")
    
    return templates.TemplateResponse(
        request=request,
        name="partials/post_response.html",
        context={
            "summary": summary,
            "breakdown": breakdown,
            "period": summary["period"],
            "transactions": transactions,
            "transactions_by_date": transactions_by_date,
            "today": today,
            "yesterday": yesterday,
            "oob_summary": True,
            "oob_breakdown": True,
            "oob_tx_list": False
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
    transactions, _ = get_filtered_transactions(db, "current_month")
    breakdown = get_category_breakdown(transactions, "current_month")
    
    return templates.TemplateResponse(
        request=request,
        name="partials/delete_response.html",
        context={
            "summary": summary,
            "breakdown": breakdown,
            "period": summary["period"],
            "oob_summary": True,
            "oob_breakdown": True,
            "oob_tx_list": False
        }
    )

@app.get("/history", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def get_history(
    request: Request,
    year: int = None,
    month: int = None,
    db: Session = Depends(get_db)
):
    today = datetime.date.today()
    current_date_str = today.strftime("%B %d, %Y")
    
    # Base month (Month 1 in the 2-month view)
    if not year or not month or month < 1 or month > 12:
        m1_year = today.year
        m1_month = today.month
    else:
        m1_year = year
        m1_month = month
        
    # Month 2 is the preceding month
    if m1_month == 1:
        m2_month = 12
        m2_year = m1_year - 1
    else:
        m2_month = m1_month - 1
        m2_year = m1_year
        
    # Navigation: older window (step back 1 month from m1)
    if m1_month == 1:
        prev_nav_year = m1_year - 1
        prev_nav_month = 12
    else:
        prev_nav_year = m1_year
        prev_nav_month = m1_month - 1
        
    # Navigation: newer window (step forward 1 month from m1, capped at current month)
    is_current_window = (m1_year == today.year and m1_month == today.month)
    if not is_current_window:
        has_newer = True
        if m1_month == 12:
            next_nav_year = m1_year + 1
            next_nav_month = 1
        else:
            next_nav_year = m1_year
            next_nav_month = m1_month + 1
    else:
        has_newer = False
        next_nav_year = None
        next_nav_month = None
        
    # Query transactions across both displayed months to accurately place calendar activity dots
    start_date = datetime.date(m2_year, m2_month, 1)
    last_day_m1 = calendar.monthrange(m1_year, m1_month)[1]
    end_date = datetime.date(m1_year, m1_month, last_day_m1)
    
    txs = db.query(models.Transaction).filter(
        models.Transaction.date >= start_date,
        models.Transaction.date <= end_date
    ).all()
    
    # Group transactions by type for each date
    tx_types_by_date = defaultdict(set)
    for tx in txs:
        tx_types_by_date[tx.date].add(tx.type)
        
    cal_obj = calendar.Calendar(firstweekday=6) # Sunday start
    
    def get_month_data(yr, mo, is_active):
        weeks = cal_obj.monthdays2calendar(yr, mo)
        grid = []
        for week in weeks:
            week_days = []
            for day, wd in week:
                if day == 0:
                    week_days.append({"day": 0, "date": None, "in_window": False, "activity": None})
                else:
                    d = datetime.date(yr, mo, day)
                    in_window = (d <= today)
                    
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
            "name": calendar.month_name[mo],
            "year": yr,
            "month": mo,
            "is_active": is_active,
            "grid": grid
        }
        
    months = [
        get_month_data(m1_year, m1_month, is_active=True),
        get_month_data(m2_year, m2_month, is_active=False)
    ]
    
    default_month = {
        "year": m1_year,
        "month": m1_month,
        "name": calendar.month_name[m1_month]
    }
    
    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "active_page": "history",
            "months": months,
            "default_month": default_month,
            "current_date": current_date_str,
            "today": today,
            "has_newer": has_newer,
            "prev_nav_year": prev_nav_year,
            "prev_nav_month": prev_nav_month,
            "next_nav_year": next_nav_year,
            "next_nav_month": next_nav_month,
            "is_current_window": is_current_window
        }
    )

@app.get("/history/month", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def get_history_month(request: Request, year: int, month: int, db: Session = Depends(get_db)):
    today = datetime.date.today()
    try:
        start_date = datetime.date(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end_date = datetime.date(year, month, last_day)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid year or month")
        
    txs = db.query(models.Transaction).filter(
        models.Transaction.date >= start_date,
        models.Transaction.date <= end_date
    ).order_by(models.Transaction.date.desc(), models.Transaction.id.desc()).all()
    
    income = sum(t.amount for t in txs if t.type == 'income')
    expense = sum(t.amount for t in txs if t.type == 'expense')
    balance = income - expense
    
    savings_rate = None
    if income > 0:
        if balance > 0:
            savings_rate = f"{int(round((balance / income) * 100))}%"
        else:
            savings_rate = "0%"
            
    # Calculate daily average days
    if year == today.year and month == today.month:
        calc_days = max(1, today.day)
    elif start_date < datetime.date(today.year, today.month, 1):
        calc_days = last_day
    else:
        calc_days = 1
        
    breakdown = get_category_breakdown(txs, custom_days=calc_days)
    
    # Group transactions by date
    txs_by_date = defaultdict(list)
    for t in txs:
        txs_by_date[t.date].append(t)
        
    month_name = calendar.month_name[month]
    
    return templates.TemplateResponse(
        request=request,
        name="partials/month_breakdown.html",
        context={
            "year": year,
            "month": month,
            "month_name": month_name,
            "start_date": start_date,
            "end_date": end_date,
            "txs": txs,
            "txs_by_date": txs_by_date,
            "income": income,
            "expense": expense,
            "balance": balance,
            "savings_rate": savings_rate,
            "breakdown": breakdown,
            "calc_days": calc_days,
            "is_current_month": (year == today.year and month == today.month)
        }
    )

@app.get("/history/day", response_class=HTMLResponse, dependencies=[Depends(get_current_user)])
def get_history_day(request: Request, date: str, db: Session = Depends(get_db)):
    try:
        selected_date = datetime.date.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
        
    txs = db.query(models.Transaction).filter(models.Transaction.date == selected_date).order_by(models.Transaction.id.desc()).all()
    
    # Calculate stats for this specific day
    income = sum(t.amount for t in txs if t.type == 'income')
    expense = sum(t.amount for t in txs if t.type == 'expense')
    balance = income - expense
    
    breakdown = get_category_breakdown(txs, custom_days=1)
    
    return templates.TemplateResponse(
        request=request,
        name="partials/day_breakdown.html",
        context={
            "selected_date": selected_date,
            "stats": {"income": income, "expense": expense, "balance": balance},
            "breakdown": breakdown,
            "transactions": txs
        }
    )

@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    if request.session.get("user"):
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        
    today = datetime.date.today()
    current_date_str = today.strftime("%B %d, %Y")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "hide_header": True,
            "current_date": current_date_str,
            "error": None
        }
    )

@app.post("/login", response_class=HTMLResponse)
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...)
):
    correct_username = os.environ.get("APP_USERNAME", "admin")
    correct_password = os.environ.get("APP_PASSWORD", "admin")
    
    is_correct_username = secrets.compare_digest(username, correct_username)
    is_correct_password = secrets.compare_digest(password, correct_password)
    
    if is_correct_username and is_correct_password:
        request.session["user"] = username
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        
    today = datetime.date.today()
    current_date_str = today.strftime("%B %d, %Y")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={
            "hide_header": True,
            "current_date": current_date_str,
            "error": "Invalid username or password"
        }
    )

@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
