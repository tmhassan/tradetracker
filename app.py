from datetime import date, timedelta, datetime
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask import send_from_directory
from sqlalchemy.orm import joinedload
from sqlalchemy import or_
import statistics
import csv
import os
from io import StringIO
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_secure_secret_key'  # Replace with a secure key in production
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trades.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Configuration for file uploads
app.config['UPLOAD_FOLDER'] = 'static/uploads/screenshots'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Max 16MB upload

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ------------------------ Models ------------------------ #
class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    target_ny_amount = db.Column(db.Float, default=360.0, nullable=False)
    target_london_amount = db.Column(db.Float, default=200.0, nullable=False)
    trade_records = db.relationship('TradeRecord', backref='account', lazy=True)
    cycles = db.relationship('Cycle', backref='account', lazy=True)
    achievements = db.relationship('Achievement', backref='account', lazy=True)

class TradeDay(db.Model):
    __tablename__ = 'trade_day'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)  # Ensure this line exists
    trade_records = db.relationship('TradeRecord', backref='trade_day', lazy=True)

class Cycle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    payout_taken = db.Column(db.Boolean, default=False)
    days_adjusted = db.Column(db.Integer, default=0)  # To track +2 or -2 adjustments
    reflection = db.Column(db.Text, nullable=True)
    trade_records = db.relationship('TradeRecord', backref='cycle', lazy=True)

class TradeRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    tradeday_id = db.Column(db.Integer, db.ForeignKey('trade_day.id'), nullable=False)
    cycle_id = db.Column(db.Integer, db.ForeignKey('cycle.id'), nullable=True)
    ny_completed = db.Column(db.Boolean, default=False)
    london_completed = db.Column(db.Boolean, default=False)
    payout_taken = db.Column(db.Boolean, default=False)
    ny_profit = db.Column(db.Float, default=0.0)      # New Field
    london_profit = db.Column(db.Float, default=0.0)  # New Field
    daily_profit = db.Column(db.Float, default=0.0)  # New Field
    trade_log = db.relationship('TradeLog', backref='trade_record', uselist=False)

    __table_args__ = (db.UniqueConstraint('account_id', 'tradeday_id', name='_account_day_uc'),)

class TradeLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    trade_record_id = db.Column(db.Integer, db.ForeignKey('trade_record.id'), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    win = db.Column(db.Boolean, default=False)
    loss = db.Column(db.Boolean, default=False)
    journal_entry = db.Column(db.Text, nullable=True)

class Achievement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    date_awarded = db.Column(db.Date, nullable=False)

class Trade(db.Model):
    __tablename__ = 'trade'
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    cycle_id = db.Column(db.Integer, db.ForeignKey('cycle.id'), nullable=False)
    trade_day_id = db.Column(db.Integer, db.ForeignKey('trade_day.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    position = db.Column(db.String(10), nullable=False)  # e.g., 'Long', 'Short'
    entry_price = db.Column(db.Float, nullable=False)
    exit_price = db.Column(db.Float, nullable=True)
    profit_loss = db.Column(db.Float, nullable=True)
    pattern = db.Column(db.String(100), nullable=True)
    mistake = db.Column(db.String(100), nullable=True)
    satisfaction = db.Column(db.String(10), nullable=True)  # 'Good', 'Bad'
    tags = db.relationship('Tag', secondary='trade_tags', backref='trades')
    screenshots = db.relationship('Screenshot', backref='trade', lazy=True)

class DiaryEntry(db.Model):
    __tablename__ = 'diary_entry'
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, unique=True)
    entry = db.Column(db.Text, nullable=True)

class TagGroup(db.Model):
    __tablename__ = 'tag_group'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    tags = db.relationship('Tag', backref='group', lazy=True)

class Tag(db.Model):
    __tablename__ = 'tag'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    group_id = db.Column(db.Integer, db.ForeignKey('tag_group.id'), nullable=True)

# Association table for many-to-many relationship between Trade and Tag
trade_tags = db.Table('trade_tags',
    db.Column('trade_id', db.Integer, db.ForeignKey('trade.id'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tag.id'), primary_key=True)
)

class Screenshot(db.Model):
    __tablename__ = 'screenshot'
    id = db.Column(db.Integer, primary_key=True)
    trade_id = db.Column(db.Integer, db.ForeignKey('trade.id'), nullable=False)
    filename = db.Column(db.String(100), nullable=False)
    annotation = db.Column(db.Text, nullable=True)

# -------------------- Helper Functions ------------------- #
def generate_trading_days(start_date, days_needed=30):
    """
    Generate trading days (excluding weekends) starting from start_date.
    """
    trading_days = []
    current = start_date
    while len(trading_days) < days_needed:
        if current.weekday() < 5:  # Monday=0, Friday=4
            trading_days.append(current)
        current += timedelta(days=1)
    return trading_days

def initialize_data():
    """
    Initialize accounts, trade days, trade records, cycles, trade logs, and achievements.
    """
    # Initialize Accounts
    if Account.query.count() == 0:
        default_accounts = ["ETF1", "ETF2", "ETF3", "APEX1"]
        for acct in default_accounts:
            db.session.add(Account(name=acct))
        db.session.commit()
        print("Initialized default accounts.")

    # Initialize TradeDays
    if TradeDay.query.count() == 0:
        start_date = date.today()
        trading_days = generate_trading_days(start_date, days_needed=30)  # 30 trading days
        for day in trading_days:
            db.session.add(TradeDay(date=day))
        db.session.commit()
        print("Initialized trading days.")

    # Initialize Cycles
    if Cycle.query.count() == 0:
        accounts = Account.query.all()
        for acct in accounts:
            # Create the first cycle
            cycle_start = date.today()
            cycle_end = cycle_start + timedelta(days=9)  # 10-day cycle
            db.session.add(Cycle(account_id=acct.id, start_date=cycle_start, end_date=cycle_end))
        db.session.commit()
        print("Initialized cycles.")

    # Initialize TradeRecords
    if TradeRecord.query.count() == 0:
        accounts = Account.query.all()
        trade_days = TradeDay.query.all()
        for acct in accounts:
            current_cycle = Cycle.query.filter_by(account_id=acct.id, payout_taken=False).order_by(Cycle.start_date.desc()).first()
            for day in trade_days:
                db.session.add(TradeRecord(account_id=acct.id, tradeday_id=day.id, cycle_id=current_cycle.id if current_cycle else None))
        db.session.commit()
        print("Initialized trade records.")

    # Initialize TradeLogs
    if TradeLog.query.count() == 0:
        trade_records = TradeRecord.query.all()
        for record in trade_records:
            db.session.add(TradeLog(trade_record_id=record.id))
        db.session.commit()
        print("Initialized trade logs.")

    # Initialize Achievements
    if Achievement.query.count() == 0:
        # Define some default achievements
        achievements = [
            {"name": "10-Day Streak", "description": "Completed trades for 10 consecutive days."},
            {"name": "100 Trades", "description": "Completed a total of 100 trades."},
            # Add more as needed
        ]
        accounts = Account.query.all()
        for acct in accounts:
            for ach in achievements:
                achievement = Achievement(account_id=acct.id, name=ach["name"],
                                          description=ach["description"], date_awarded=date.today())
                db.session.add(achievement)
        db.session.commit()
        print("Initialized achievements.")

# --------------------- Application Setup ------------------ #
@app.before_first_request
def setup():
    """
    Initialize database and data before the first request.
    """
    db.create_all()
    initialize_data()

# ------------------------ Routes ------------------------- #
# Context Processor to inject common variables
@app.context_processor
def inject_common_variables():
    accounts = Account.query.order_by(Account.name).all()
    selected_account_name = request.args.get("selected_account", accounts[0].name if accounts else None)
    selected_account = Account.query.filter_by(name=selected_account_name).first() if accounts else None
    current_cycle = Cycle.query.filter_by(account_id=selected_account.id).order_by(Cycle.start_date.desc()).first() if selected_account else None
    return dict(accounts=accounts, selected_account=selected_account, account=selected_account, cycle=current_cycle)


@app.route("/", methods=["GET", "POST"])
def index():
    """
    Main dashboard route. Handles displaying the dashboard, adding accounts, trade days,
    updating trade records, and exporting data.
    """
    accounts = Account.query.order_by(Account.name).all()
    selected_account = None

    if request.method == "GET":
        selected_account_name = request.args.get("selected_account", accounts[0].name if accounts else None)
        selected_account = Account.query.filter_by(name=selected_account_name).first()
    else:
        # Handle POST request
        selected_account_name = request.form.get("account_name")
        selected_account = Account.query.filter_by(name=selected_account_name).first()

    trade_days = TradeDay.query.order_by(TradeDay.date).all()
    current_cycle = Cycle.query.filter_by(account_id=selected_account.id if selected_account else None, payout_taken=False).order_by(Cycle.start_date.desc()).first()

    # Initialize metrics
    total_profit = 0.0
    win_count = 0
    total_trades = 0

    if current_cycle:
        trade_records = TradeRecord.query.filter_by(cycle_id=current_cycle.id).all()
        total_profit = sum(record.daily_profit for record in trade_records)
        win_count = sum(1 for record in trade_records if record.daily_profit > 0)
        total_trades = len(trade_records) * 2  # NY and London trades

    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0
    avg_profit = (total_profit / total_trades) if total_trades > 0 else 0.0

    if request.method == "POST":
        # Determine the form action based on hidden inputs
        if "add_account" in request.form:
            # Add a new account
            new_account = request.form.get("new_account_name", "").strip()
            target_ny = request.form.get("target_ny", 360.0)
            target_london = request.form.get("target_london", 200.0)
            if new_account:
                existing_account = Account.query.filter_by(name=new_account).first()
                if existing_account:
                    flash(f"Account '{new_account}' already exists.", "warning")
                else:
                    try:
                        target_ny = float(target_ny)
                        target_london = float(target_london)
                    except ValueError:
                        flash("Invalid target amounts. Please enter numeric values.", "danger")
                        return redirect(url_for("index"))
                    account = Account(name=new_account, target_ny_amount=target_ny, target_london_amount=target_london)
                    db.session.add(account)
                    db.session.commit()
                    # Create cycles for the new account
                    cycle_start = date.today()
                    cycle_end = cycle_start + timedelta(days=9)
                    cycle = Cycle(account_id=account.id, start_date=cycle_start, end_date=cycle_end)
                    db.session.add(cycle)
                    db.session.commit()
                    # Create trade records for existing trade days
                    for day in trade_days:
                        trade_record = TradeRecord(account_id=account.id, tradeday_id=day.id, cycle_id=cycle.id)
                        db.session.add(trade_record)
                    db.session.commit()
                    # Initialize TradeLogs for new trade records
                    new_trade_records = TradeRecord.query.filter_by(account_id=account.id).all()
                    for record in new_trade_records:
                        db.session.add(TradeLog(trade_record_id=record.id))
                    db.session.commit()
                    flash(f"Account '{new_account}' added successfully.", "success")
            else:
                flash("Account name cannot be empty.", "danger")
            return redirect(url_for("index"))

        elif "add_trade_day" in request.form:
            # Add a new trade day
            new_trade_date_str = request.form.get("new_trade_date", "").strip()
            try:
                new_trade_date = date.fromisoformat(new_trade_date_str)
                existing_day = TradeDay.query.filter_by(date=new_trade_date).first()
                if existing_day:
                    flash(f"Trade day '{new_trade_date}' already exists.", "warning")
                else:
                    trade_day = TradeDay(date=new_trade_date)
                    db.session.add(trade_day)
                    db.session.commit()
                    # Assign trade records to the current active cycle for each account
                    accounts = Account.query.all()
                    for acct in accounts:
                        current_cycle = Cycle.query.filter_by(account_id=acct.id, payout_taken=False).order_by(Cycle.start_date.desc()).first()
                        trade_record = TradeRecord(account_id=acct.id, tradeday_id=trade_day.id, cycle_id=current_cycle.id if current_cycle else None)
                        db.session.add(trade_record)
                        # Initialize TradeLog for the new TradeRecord
                        db.session.add(TradeLog(trade_record_id=trade_record.id))
                    db.session.commit()
                    flash(f"Trade day '{new_trade_date}' added successfully.", "success")
            except ValueError:
                flash("Invalid date format. Please use YYYY-MM-DD.", "danger")
            return redirect(url_for("index"))

        elif "export_csv" in request.form:
            # Export data as CSV
            account_name = request.form.get("selected_account", "").strip()
            account = Account.query.filter_by(name=account_name).first()
            if not account:
                flash("Selected account does not exist.", "danger")
                return redirect(url_for("index"))
            records = TradeRecord.query.filter_by(account_id=account.id).join(TradeDay).order_by(TradeDay.date).all()
            si = StringIO()
            cw = csv.writer(si)
            # Write headers
            cw.writerow(["Date", "NY Completed", "London Completed", "Payout Taken", "NY Profit", "London Profit", "Daily Profit"])
            # Write data
            for record in records:
                cw.writerow([
                    record.trade_day.date.strftime('%Y-%m-%d'),
                    record.ny_completed,
                    record.london_completed,
                    record.payout_taken,
                    record.ny_profit,
                    record.london_profit,
                    record.daily_profit
                ])
            output = si.getvalue()
            return (output, 200, {
                'Content-Type': 'text/csv',
                'Content-Disposition': f'attachment;filename={account.name}_trade_data.csv'
            })

        elif "edit_account" in request.form:
            # Edit account targets
            account_id = request.form.get("account_id")
            target_ny = request.form.get("edit_target_ny", 360.0)
            target_london = request.form.get("edit_target_london", 200.0)
            account = Account.query.get(account_id)
            if account:
                try:
                    account.target_ny_amount = float(target_ny)
                    account.target_london_amount = float(target_london)
                except ValueError:
                    flash("Invalid target amounts. Please enter numeric values.", "danger")
                    return redirect(url_for("index"))
                db.session.commit()
                flash(f"Account '{account.name}' targets updated successfully.", "success")
            else:
                flash("Account not found.", "danger")
            return redirect(url_for("index"))

        elif "award_achievement" in request.form:
            # Award a new achievement
            account_id = request.form.get("award_account_id")
            achievement_name = request.form.get("achievement_name", "").strip()
            achievement_description = request.form.get("achievement_description", "").strip()
            account = Account.query.get(account_id)
            if account and achievement_name and achievement_description:
                new_achievement = Achievement(
                    account_id=account.id,
                    name=achievement_name,
                    description=achievement_description,
                    date_awarded=date.today()
                )
                db.session.add(new_achievement)
                db.session.commit()
                flash(f"Achievement '{achievement_name}' awarded to {account.name}.", "success")
            else:
                flash("Invalid achievement data.", "danger")
            return redirect(url_for("achievements", account_id=account_id))

        elif "add_trade_log" in request.form:
            # Handle trade log entries
            trade_record_id = request.form.get("trade_record_id")
            notes = request.form.get("notes", "").strip()
            win = True if request.form.get("win") == "on" else False
            loss = True if request.form.get("loss") == "on" else False

            trade_log = TradeLog.query.filter_by(trade_record_id=trade_record_id).first()
            if trade_log:
                trade_log.notes = notes
                trade_log.win = win
                trade_log.loss = loss

                # Auto-generate journal entry
                trade_record = TradeRecord.query.get(trade_record_id)
                journal = f"Date: {trade_record.trade_day.date.strftime('%b %d, %Y')}\n"
                journal += f"NY Trade Completed: {'Yes' if trade_record.ny_completed else 'No'}\n"
                journal += f"London Trade Completed: {'Yes' if trade_record.london_completed else 'No'}\n"
                journal += f"NY Profit: ${trade_record.ny_profit:.2f}\n"
                journal += f"London Profit: ${trade_record.london_profit:.2f}\n"
                journal += f"Daily Profit: ${trade_record.daily_profit:.2f}\n"
                journal += f"Win: {'Yes' if win else 'No'}\n"
                journal += f"Loss: {'Yes' if loss else 'No'}\n"
                journal += f"Notes: {notes}\n"

                trade_log.journal_entry = journal

                db.session.add(trade_log)
                db.session.commit()
                flash("Trade log updated successfully.", "success")
            else:
                flash("Trade log not found.", "danger")
            return redirect(url_for("index"))

        else:
            # Handle trade record updates with separate NY and London profits
            account_name = request.form.get("account_name", "").strip()
            account = Account.query.filter_by(name=account_name).first()
            if not account:
                flash("Selected account does not exist.", "danger")
                return redirect(url_for("index"))

        # Handle updating trade records
        if selected_account:
            # Handle updating trade records
            for record in trade_records:
                ny_profit_key = f"ny_profit_{record.id}"
                london_profit_key = f"london_profit_{record.id}"
                payout_key = f"payout_{record.id}"

                # Update NY Profit
                if ny_profit_key in request.form:
                    try:
                        ny_profit = float(request.form.get(ny_profit_key, 0.0))
                        record.ny_profit = ny_profit
                        record.ny_completed = ny_profit > 0
                    except ValueError:
                        flash(f"Invalid NY profit for record ID {record.id}.", "danger")

                # Update London Profit
                if london_profit_key in request.form:
                    try:
                        london_profit = float(request.form.get(london_profit_key, 0.0))
                        record.london_profit = london_profit
                        record.london_completed = london_profit > 0
                    except ValueError:
                        flash(f"Invalid London profit for record ID {record.id}.", "danger")

                # Update Daily Profit
                record.daily_profit = record.ny_profit + record.london_profit

                # Update Payout Taken
                record.payout_taken = payout_key in request.form

                db.session.add(record)

            try:
                db.session.commit()
                flash("Trade records updated successfully.", "success")
            except IntegrityError:
                db.session.rollback()
                flash("An error occurred while updating trade records.", "danger")

            # Redirect to the same page with the selected account preserved
            return redirect(url_for("index", selected_account=selected_account.name if selected_account else None))
        else:
            flash("No account selected for updating.", "warning")
            return redirect(url_for("index"))

    # Safely set target amounts to 0.0 if selected_account is None
    target_ny_amount = selected_account.target_ny_amount if selected_account else 0.0
    target_london_amount = selected_account.target_london_amount if selected_account else 0.0

    # If GET request, render the dashboard
    return render_template("index.html", accounts=accounts, selected_account=selected_account, account=selected_account,
                           trade_days=trade_days, current_cycle=current_cycle, total_profit=total_profit, win_rate=win_rate, avg_profit=avg_profit,
                           target_ny_amount=selected_account.target_ny_amount if selected_account else 0.0,
                           target_london_amount=selected_account.target_london_amount if selected_account else 0.0)

@app.route("/all_accounts_data")
def all_accounts_data():
    accounts = Account.query.all()
    accounts_data = []
    for account in accounts:
        current_cycle = Cycle.query.filter_by(account_id=account.id, payout_taken=False).order_by(Cycle.start_date.desc()).first()
        if current_cycle:
            trade_records = TradeRecord.query.filter_by(cycle_id=current_cycle.id).all()
            total_profit = sum(record.daily_profit for record in trade_records)
            ny_completed = sum(1 for record in trade_records if record.ny_profit > 0)
            ny_pending = sum(1 for record in trade_records if record.ny_profit <= 0)
            london_completed = sum(1 for record in trade_records if record.london_profit > 0)
            london_pending = sum(1 for record in trade_records if record.london_profit <= 0)
        else:
            total_profit = 0.0
            ny_completed = 0
            ny_pending = 0
            london_completed = 0
            london_pending = 0

        accounts_data.append({
            "id": account.id,
            "name": account.name,
            "total_profit": total_profit,
            "ny_completed_count": ny_completed,
            "ny_pending_count": ny_pending,
            "london_completed_count": london_completed,
            "london_pending_count": london_pending,
            "target_ny_amount": account.target_ny_amount,
            "target_london_amount": account.target_london_amount,
        })

    return jsonify({"accounts_data": accounts_data})

@app.route("/trade_goals_data/<account_name>")
def trade_goals_data(account_name):
    account = Account.query.filter_by(name=account_name).first()
    if not account:
        return jsonify({"error": "Account not found."}), 404

    try:
        # Calculate progress towards trade goals
        current_cycle = Cycle.query.filter_by(account_id=account.id, payout_taken=False).order_by(Cycle.start_date.desc()).first()
        if not current_cycle:
            return jsonify({"error": "No active cycle found."}), 404

        trade_records = TradeRecord.query.filter_by(cycle_id=current_cycle.id).all()
        total_ny_profit = sum(record.ny_profit for record in trade_records)
        total_london_profit = sum(record.london_profit for record in trade_records)
        total_profit = total_ny_profit + total_london_profit

        return jsonify({
            "ny_progress": min((total_ny_profit / account.target_ny_amount) * 100, 100) if account.target_ny_amount > 0 else 0,
            "london_progress": min((total_london_profit / account.target_london_amount) * 100, 100) if account.target_london_amount > 0 else 0,
            "total_profit_progress": min((total_profit / (account.target_ny_amount + account.target_london_amount)) * 100, 100) if (account.target_ny_amount + account.target_london_amount) > 0 else 0
        })
    except Exception as e:
        logger.error(f"Error fetching trade goals data for {account_name}: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@app.route("/cumulative_pnl/<account_name>")
def cumulative_pnl(account_name):
    account = Account.query.filter_by(name=account_name).first()
    if not account:
        return jsonify({"error": "Account not found."}), 404

    try:
        # Corrected query with join
        trade_records = TradeRecord.query \
            .join(TradeDay) \
            .filter(TradeRecord.account_id == account.id) \
            .order_by(TradeDay.date) \
            .all()

        # Process data for Cumulative P&L
        dates = [record.trade_day.date.strftime('%Y-%m-%d') for record in trade_records]
        ny_profits = [record.ny_profit for record in trade_records]
        london_profits = [record.london_profit for record in trade_records]
        cumulative_pnl = []
        total = 0.0
        for record in trade_records:
            total += record.daily_profit
            cumulative_pnl.append(total)

        return jsonify({
            "dates": dates,
            "ny_profits": ny_profits,
            "london_profits": london_profits,
            "cumulative_pnl": cumulative_pnl
        })
    except Exception as e:
        app.logger.error(f"Error fetching cumulative P&L for {account_name}: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@app.route("/trade_completion_rates/<account_name>")
def trade_completion_rates(account_name):
    account = Account.query.filter_by(name=account_name).first()
    if not account:
        return jsonify({"error": "Account not found."}), 404

    try:
        current_cycle = Cycle.query.filter_by(account_id=account.id, payout_taken=False).order_by(Cycle.start_date.desc()).first()
        if not current_cycle:
            return jsonify({"error": "No active cycle found."}), 404

        trade_records = TradeRecord.query.filter_by(cycle_id=current_cycle.id).all()
        ny_completed = sum(1 for record in trade_records if record.ny_completed)
        ny_pending = sum(1 for record in trade_records if not record.ny_completed)
        london_completed = sum(1 for record in trade_records if record.london_completed)
        london_pending = sum(1 for record in trade_records if not record.london_completed)

        return jsonify({
            "ny_completed_count": ny_completed,
            "ny_pending_count": ny_pending,
            "london_completed_count": london_completed,
            "london_pending_count": london_pending
        })
    except Exception as e:
        logger.error(f"Error fetching trade completion rates for {account_name}: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@app.route("/profit_loss_cycles/<account_name>")
def profit_loss_cycles(account_name):
    account = Account.query.filter_by(name=account_name).first()
    if not account:
        return jsonify({"error": "Account not found."}), 404

    try:
        cycles = Cycle.query.filter_by(account_id=account.id).order_by(Cycle.start_date).all()
        cycle_dates = [cycle.start_date.strftime('%Y-%m-%d') for cycle in cycles]
        cycle_profits = [sum(record.daily_profit for record in cycle.trade_records) for cycle in cycles]

        return jsonify({
            "cycle_dates": cycle_dates,
            "cycle_profits": cycle_profits
        })
    except Exception as e:
        logger.error(f"Error fetching profit/loss over cycles for {account_name}: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@app.route("/take_payout/<int:cycle_id>", methods=["POST"])
def take_payout(cycle_id):
    """
    Mark payout as taken for a specific cycle and create a new cycle.
    """
    cycle = Cycle.query.get_or_404(cycle_id)
    if cycle.payout_taken:
        flash("Payout has already been taken for this cycle.", "warning")
    else:
        cycle.payout_taken = True
        db.session.add(cycle)
        db.session.commit()
        # Create a new cycle
        new_start_date = cycle.end_date + timedelta(days=1)
        new_end_date = new_start_date + timedelta(days=9)
        new_cycle = Cycle(account_id=cycle.account_id, start_date=new_start_date, end_date=new_end_date)
        db.session.add(new_cycle)
        db.session.commit()
        # Assign trade records to the new cycle
        trade_records = TradeRecord.query.filter_by(account_id=cycle.account_id, cycle_id=cycle.id).all()
        for record in trade_records:
            if new_cycle.start_date <= record.trade_day.date <= new_cycle.end_date:
                record.cycle_id = new_cycle.id
                db.session.add(record)
        db.session.commit()
        flash("Payout taken and new cycle started successfully.", "success")
    return redirect(url_for("index"))

@app.route("/trade_log/<int:trade_record_id>", methods=["GET", "POST"])
def trade_log(trade_record_id):
    """
    Handle trade log entries for a specific trade record.
    """
    trade_record = TradeRecord.query.get_or_404(trade_record_id)
    trade_log = TradeLog.query.filter_by(trade_record_id=trade_record.id).first()
    accounts = Account.query.order_by(Account.name).all()
    selected_account = trade_record.account if trade_record.account else None

    if request.method == "POST":
        notes = request.form.get("notes", "").strip()
        win = True if request.form.get("win") == "on" else False
        loss = True if request.form.get("loss") == "on" else False

        if trade_log:
            trade_log.notes = notes
            trade_log.win = win
            trade_log.loss = loss

            # Auto-generate journal entry
            journal = f"Date: {trade_record.trade_day.date.strftime('%b %d, %Y')}\n"
            journal += f"NY Trade Completed: {'Yes' if trade_record.ny_completed else 'No'}\n"
            journal += f"London Trade Completed: {'Yes' if trade_record.london_completed else 'No'}\n"
            journal += f"NY Profit: ${trade_record.ny_profit:.2f}\n"
            journal += f"London Profit: ${trade_record.london_profit:.2f}\n"
            journal += f"Daily Profit: ${trade_record.daily_profit:.2f}\n"
            journal += f"Win: {'Yes' if win else 'No'}\n"
            journal += f"Loss: {'Yes' if loss else 'No'}\n"
            journal += f"Notes: {notes}\n"

            trade_log.journal_entry = journal

            db.session.add(trade_log)
            db.session.commit()
            flash("Trade log updated successfully.", "success")
        else:
            flash("Trade log not found.", "danger")
        return redirect(url_for("index"))

    return render_template("trade_log.html", trade_record=trade_record, trade_log=trade_log,
                           accounts=accounts, selected_account=selected_account)

@app.route("/cycle_review/<int:cycle_id>", methods=["GET"])
def cycle_review(cycle_id):
    cycle = Cycle.query.get(cycle_id)
    if not cycle:
        flash("Cycle not found.", "warning")
        return redirect(url_for("index"))  # Redirect to homepage or appropriate page

    # Fetch related data for the cycle as needed
    trade_records = TradeRecord.query.filter_by(cycle_id=cycle_id).all()

    # Calculate additional metrics if needed
    total_wins = sum(1 for record in trade_records if record.ny_completed or record.london_completed)
    total_losses = sum(1 for record in trade_records if not (record.ny_completed or record.london_completed))
    total_ny_completed = sum(1 for record in trade_records if record.ny_completed)
    total_london_completed = sum(1 for record in trade_records if record.london_completed)
    total_profit = sum(record.daily_profit for record in trade_records)

    return render_template(
        "cycle_review.html",
        cycle=cycle,
        trade_records=trade_records,
        total_wins=total_wins,
        total_losses=total_losses,
        total_ny_completed=total_ny_completed,
        total_london_completed=total_london_completed,
        total_profit=total_profit
    )

@app.route("/achievements/<int:account_id>", methods=["GET", "POST"])
def achievements(account_id):
    """
    Display and manage achievements for a specific account.
    """
    account = Account.query.get_or_404(account_id)
    achievements = Achievement.query.filter_by(account_id=account.id).all()
    accounts = Account.query.order_by(Account.name).all()
    selected_account = account

    # Fetch the latest cycle for the selected account
    cycle = Cycle.query.filter_by(account_id=account.id).order_by(Cycle.start_date.desc()).first()

    if request.method == "POST":
        # Handle awarding new achievement
        achievement_name = request.form.get("achievement_name", "").strip()
        achievement_description = request.form.get("achievement_description", "").strip()
        if achievement_name and achievement_description:
            new_achievement = Achievement(
                account_id=account.id,
                name=achievement_name,
                description=achievement_description,
                date_awarded=date.today()
            )
            db.session.add(new_achievement)
            db.session.commit()
            flash(f"Achievement '{achievement_name}' awarded to {account.name}.", "success")
        else:
            flash("Invalid achievement data.", "danger")
        return redirect(url_for("achievements", account_id=account_id))

    return render_template(
        "achievements.html",
        account=account,
        achievements=achievements,
        accounts=accounts,
        selected_account=selected_account,
        cycle=cycle  # Pass the cycle to the template
    )

@app.route("/export_cycle_csv/<int:cycle_id>", methods=["POST"])
def export_cycle_csv(cycle_id):
    """
    Export cycle summary as CSV.
    """
    cycle = Cycle.query.get_or_404(cycle_id)
    trade_records = TradeRecord.query.filter_by(cycle_id=cycle.id).all()

    si = StringIO()
    cw = csv.writer(si)
    # Write headers
    cw.writerow(["Date", "NY Completed", "London Completed", "Payout Taken", "NY Profit", "London Profit", "Daily Profit"])
    # Write data
    for record in trade_records:
        cw.writerow([
            record.trade_day.date.strftime('%Y-%m-%d'),
            record.ny_completed,
            record.london_completed,
            record.payout_taken,
            record.ny_profit,
            record.london_profit,
            record.daily_profit
        ])
    output = si.getvalue()
    return (output, 200, {
        'Content-Type': 'text/csv',
        'Content-Disposition': f'attachment;filename=Cycle_{cycle.id}_Summary.csv'
    })

@app.route("/completion_data/<account_name>")
def completion_data(account_name):
    """
    Fetch completion data for NY and London trades.
    """
    account = Account.query.filter_by(name=account_name).first()
    if not account:
        return jsonify({"error": "Account not found"}), 404

    ny_completed_count = TradeRecord.query.filter_by(account_id=account.id, ny_completed=True).count()
    ny_pending_count = TradeRecord.query.filter_by(account_id=account.id, ny_completed=False).count()
    london_completed_count = TradeRecord.query.filter_by(account_id=account.id, london_completed=True).count()
    london_pending_count = TradeRecord.query.filter_by(account_id=account.id, london_completed=False).count()

    return jsonify({
        "ny_completed_count": ny_completed_count,
        "ny_pending_count": ny_pending_count,
        "london_completed_count": london_completed_count,
        "london_pending_count": london_pending_count
    })

@app.route("/profit_loss_data/<account_name>")
def profit_loss_data(account_name):
    """
    Fetch profit/loss data per cycle for the chart.
    """
    account = Account.query.filter_by(name=account_name).first()
    if not account:
        return jsonify({"error": "Account not found"}), 404

    cycles = Cycle.query.filter_by(account_id=account.id).order_by(Cycle.start_date).all()
    cycle_dates = [f"{cycle.start_date.strftime('%b %d')} - {cycle.end_date.strftime('%b %d')}" for cycle in cycles]
    cycle_profits = [TradeRecord.query.filter_by(cycle_id=cycle.id).with_entities(db.func.sum(TradeRecord.daily_profit)).scalar() or 0.0 for cycle in cycles]

    return jsonify({
        "cycle_dates": cycle_dates,
        "cycle_profits": cycle_profits
    })

@app.route("/account_data/<account_name>")
def account_data(account_name):
    """
    Fetch account-specific data for metrics and charts.
    """
    account = Account.query.filter_by(name=account_name).first()
    if not account:
        return jsonify({"error": "Account not found."}), 404

    try:
        trade_records = TradeRecord.query \
            .join(TradeDay) \
            .filter(TradeRecord.account_id == account.id) \
            .order_by(TradeDay.date) \
            .all()

        # Process trade_records as needed
        # For example, serialize the data for JSON response
        serialized_records = [
            {
                "id": record.id,
                "ny_profit": record.ny_profit,
                "london_profit": record.london_profit,
                "daily_profit": record.daily_profit,
                "payout_taken": record.payout_taken,
                "trade_day": record.trade_day.date.strftime('%Y-%m-%d') if record.trade_day.date else None
            }
            for record in trade_records
        ]

        return jsonify({"trade_records": serialized_records})
    except Exception as e:
        app.logger.error(f"Error fetching account data for {account_name}: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@app.route("/delete_account/<int:account_id>", methods=["POST"])
def delete_account(account_id):
    """
    Delete an account and its associated trade records, cycles, trade logs, and achievements.
    """
    account = Account.query.get_or_404(account_id)
    db.session.delete(account)
    db.session.commit()
    flash(f"Account '{account.name}' and all associated data deleted successfully.", "success")
    return redirect(url_for("index"))

@app.route("/delete_trade_day/<int:trade_day_id>", methods=["POST"])
def delete_trade_day(trade_day_id):
    """
    Delete a trade day and its associated trade records.
    """
    trade_day = TradeDay.query.get_or_404(trade_day_id)
    db.session.delete(trade_day)
    db.session.commit()
    flash(f"Trade day '{trade_day.date}' and all associated trade records deleted successfully.", "success")
    return redirect(url_for("index"))

# Allowed extensions for screenshots
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/add_trade/<int:account_id>", methods=["GET", "POST"])
def add_trade(account_id):
    account = Account.query.get_or_404(account_id)
    cycles = Cycle.query.filter_by(account_id=account.id).order_by(Cycle.start_date.desc()).all()
    trade_days = TradeDay.query.order_by(TradeDay.date.desc()).all()
    tag_groups = TagGroup.query.order_by(TagGroup.name).all()
    tags = Tag.query.order_by(Tag.name).all()

    # Determine the current cycle (e.g., the latest cycle)
    current_cycle = Cycle.query.filter_by(account_id=account.id).order_by(Cycle.start_date.desc()).first()

    if request.method == "POST":
        # Extract form data
        cycle_id = request.form.get("cycle_id", type=int)
        trade_day_id = request.form.get("trade_day_id", type=int)
        trade_date_str = request.form.get("trade_date")
        position = request.form.get("position")
        entry_price = request.form.get("entry_price", type=float)
        exit_price = request.form.get("exit_price", type=float)
        profit_loss = request.form.get("profit_loss", type=float)
        pattern = request.form.get("pattern")
        mistake = request.form.get("mistake")
        satisfaction = request.form.get("satisfaction")
        selected_tags = request.form.getlist("tags")

        # Convert trade_date_str to date object
        try:
            trade_date = datetime.strptime(trade_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash("Invalid date format. Please use YYYY-MM-DD.", "danger")
            return redirect(request.url)

        # Create new Trade
        new_trade = Trade(
            account_id=account.id,
            cycle_id=cycle_id,
            trade_day_id=trade_day_id,
            date=trade_date,
            position=position,
            entry_price=entry_price,
            exit_price=exit_price,
            profit_loss=profit_loss,
            pattern=pattern,
            mistake=mistake,
            satisfaction=satisfaction
        )

        # Add tags
        for tag_id in selected_tags:
            tag = Tag.query.get(tag_id)
            if tag:
                new_trade.tags.append(tag)

        # Handle file uploads for screenshots
        files = request.files.getlist("screenshots")
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                # Create Screenshot record
                screenshot = Screenshot(
                    trade=new_trade,
                    filename=filename
                )
                db.session.add(screenshot)

        # Add and commit to DB
        try:
            db.session.add(new_trade)
            db.session.commit()
            flash("Trade added successfully.", "success")
            return redirect(url_for("view_trades", account_id=account.id))
        except Exception as e:
            db.session.rollback()
            flash(f"An error occurred while adding the trade: {str(e)}", "danger")
            return redirect(request.url)

    return render_template(
        "add_trade.html",
        account=account,
        cycles=cycles,
        trade_days=trade_days,
        tag_groups=tag_groups,
        tags=tags,
        cycle=current_cycle  # Pass the current cycle to the template
    )

@app.route("/trades/<int:account_id>", methods=["GET"])
def view_trades(account_id):
    account = Account.query.get_or_404(account_id)
    trades = Trade.query.filter_by(account_id=account.id).join(Cycle).join(TradeDay).all()

    # Filtering parameters
    filter_date = request.args.get("filter_date")
    filter_position = request.args.get("filter_position")
    filter_pattern = request.args.get("filter_pattern")
    filter_mistake = request.args.get("filter_mistake")
    filter_satisfaction = request.args.get("filter_satisfaction")
    filter_tags = request.args.getlist("filter_tags")

    # Apply filters
    if filter_date:
        trades = Trade.query.filter_by(account_id=account.id, date=filter_date).all()
    if filter_position:
        trades = Trade.query.filter_by(account_id=account.id, position=filter_position).all()
    if filter_pattern:
        trades = Trade.query.filter(Trade.pattern.contains(filter_pattern)).all()
    if filter_mistake:
        trades = Trade.query.filter(Trade.mistake.contains(filter_mistake)).all()
    if filter_satisfaction:
        trades = Trade.query.filter_by(account_id=account.id, satisfaction=filter_satisfaction).all()
    if filter_tags:
        trades = Trade.query.filter(Trade.tags.any(Tag.id.in_(filter_tags))).all()

    tag_groups = TagGroup.query.order_by(TagGroup.name).all()
    tags = Tag.query.order_by(Tag.name).all()

    return render_template(
        "view_trades.html",
        account=account,
        trades=trades,
        tag_groups=tag_groups,
        tags=tags,
        filter_date=filter_date,
        filter_position=filter_position,
        filter_pattern=filter_pattern,
        filter_mistake=filter_mistake,
        filter_satisfaction=filter_satisfaction,
        filter_tags=filter_tags
    )

@app.route("/edit_trade/<int:trade_id>", methods=["GET", "POST"])
def edit_trade(trade_id):
    trade = Trade.query.get_or_404(trade_id)
    account = trade.account
    cycles = Cycle.query.filter_by(account_id=account.id).order_by(Cycle.start_date.desc()).all()
    trade_days = TradeDay.query.order_by(TradeDay.date.desc()).all()
    tag_groups = TagGroup.query.order_by(TagGroup.name).all()
    tags = Tag.query.order_by(Tag.name).all()

    if request.method == "POST":
        # Update trade details
        trade.cycle_id = request.form.get("cycle_id", type=int)
        trade.trade_day_id = request.form.get("trade_day_id", type=int)
        trade.date = request.form.get("trade_date")
        trade.position = request.form.get("position")
        trade.entry_price = request.form.get("entry_price", type=float)
        trade.exit_price = request.form.get("exit_price", type=float)
        trade.profit_loss = request.form.get("profit_loss", type=float)
        trade.pattern = request.form.get("pattern")
        trade.mistake = request.form.get("mistake")
        trade.satisfaction = request.form.get("satisfaction")

        # Update tags
        selected_tags = request.form.getlist("tags")
        trade.tags = []  # Clear existing tags
        for tag_id in selected_tags:
            tag = Tag.query.get(tag_id)
            if tag:
                trade.tags.append(tag)

        # Handle new screenshot uploads
        files = request.files.getlist("screenshots")
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                # Create Screenshot record
                screenshot = Screenshot(
                    trade=trade,
                    filename=filename
                )
                db.session.add(screenshot)

        db.session.commit()
        flash("Trade updated successfully.", "success")
        return redirect(url_for("view_trades", account_id=account.id))

    return render_template(
        "edit_trade.html",
        trade=trade,
        account=account,
        cycles=cycles,
        trade_days=trade_days,
        tag_groups=tag_groups,
        tags=tags
    )

@app.route("/delete_trade/<int:trade_id>", methods=["POST"])
def delete_trade(trade_id):
    trade = Trade.query.get_or_404(trade_id)
    account_id = trade.account.id

    # Delete associated screenshots from filesystem
    for screenshot in trade.screenshots:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], screenshot.filename)
        if os.path.exists(filepath):
            os.remove(filepath)

    # Delete trade from DB
    db.session.delete(trade)
    db.session.commit()
    flash("Trade deleted successfully.", "success")
    return redirect(url_for("view_trades", account_id=account_id))

@app.route("/diary/<int:account_id>", methods=["GET", "POST"])
def diary(account_id):
    account = Account.query.get_or_404(account_id)
    today = date.today()
    diary_entry = DiaryEntry.query.filter_by(account_id=account.id, date=today).first()

    if request.method == "POST":
        entry_text = request.form.get("entry")
        if diary_entry:
            diary_entry.entry = entry_text
        else:
            diary_entry = DiaryEntry(
                account_id=account.id,
                date=today,
                entry=entry_text
            )
            db.session.add(diary_entry)
        db.session.commit()
        flash("Diary entry saved successfully.", "success")
        return redirect(url_for("diary", account_id=account.id))

    return render_template(
        "diary.html",
        account=account,
        diary_entry=diary_entry
    )

@app.route("/create_tag_group", methods=["POST"])
def create_tag_group():
    group_name = request.form.get("group_name").strip()
    if group_name:
        existing_group = TagGroup.query.filter_by(name=group_name).first()
        if not existing_group:
            new_group = TagGroup(name=group_name)
            db.session.add(new_group)
            db.session.commit()
            flash(f"Tag group '{group_name}' created.", "success")
        else:
            flash(f"Tag group '{group_name}' already exists.", "warning")
    else:
        flash("Tag group name cannot be empty.", "danger")
    return redirect(request.referrer)

@app.route("/create_tag", methods=["POST"])
def create_tag():
    tag_name = request.form.get("tag_name").strip()
    group_id = request.form.get("group_id", type=int)
    if tag_name:
        existing_tag = Tag.query.filter_by(name=tag_name).first()
        if not existing_tag:
            new_tag = Tag(name=tag_name, group_id=group_id if group_id else None)
            db.session.add(new_tag)
            db.session.commit()
            flash(f"Tag '{tag_name}' created.", "success")
        else:
            flash(f"Tag '{tag_name}' already exists.", "warning")
    else:
        flash("Tag name cannot be empty.", "danger")
    return redirect(request.referrer)

# --------------------------------------------------------- #

if __name__ == "__main__":
    app.run(debug=True)
