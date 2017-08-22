from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from passlib.apps import custom_app_context as pwd_context
from tempfile import mkdtemp

from helpers import *

# configure application
app = Flask(__name__)

# ensure responses aren't cached
if app.config["DEBUG"]:
    @app.after_request
    def after_request(response):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Expires"] = 0
        response.headers["Pragma"] = "no-cache"
        return response

# custom filter
app.jinja_env.filters["usd"] = usd

# configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

@app.route("/")
@login_required
def index():
    user_id = session["user_id"]
    total = 0
    # get user
    rows = db.execute("SELECT user_shares.amount as amount, companies.symbol as symbol, companies.name as name from user_shares JOIN companies ON user_shares.company_id = companies.id WHERE user_shares.user_id = :user_id", user_id = user_id)
    for row in rows:
        row["price"] = lookup(row["symbol"])["price"]
        total += row["amount"] * row["price"]

    cash = db.execute("SELECT * from users WHERE id = :user_id", user_id = user_id)[0]["cash"]
    total += cash

    return render_template("index.html", shares=rows, cash=cash, total=total)

@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock."""
    if request.method == "POST":
        # transaction types: 1 - buy, 2 - sell
        transaction_type_id = 1
        user_id = session["user_id"]
        symbol = request.form["symbol"]
        amount = int(request.form["amount"])
        if symbol == "" or lookup(symbol) == None or amount <= 0:
            return apology("TODO")

        # get share's current value
        company = lookup(symbol)
        share_value = company["price"]

        # check if user has enough credit to buy those shares
        cash_available = db.execute("SELECT cash FROM users WHERE id = :id", id=session["user_id"])[0]["cash"]
        if cash_available < share_value * amount:
            flash("Not enough cash", "danger")
            return apology("not enough cash")
        # insert company into companies if not already there
        row = db.execute("SELECT * FROM companies WHERE symbol = :symbol", symbol=symbol)
        if len(row) == 0:
            company_id = db.execute("INSERT INTO companies (symbol, name) VALUES (:symbol, :name)", symbol = symbol, name = company["name"])
        else:
            company_id = row[0]["id"]

        # insert transacion into transactions history
        print("transaction_type_id: {} - user_id: {} - company_id: {}, amount: {}, share_value: {}".format(transaction_type_id, user_id, company_id, amount, share_value))
        db.execute("INSERT INTO transactions (transaction_type_id, user_id, company_id, amount, price) VALUES(:transaction_type_id, :user_id, :company_id, :amount, :price)", transaction_type_id = transaction_type_id, user_id = session["user_id"], company_id = company_id, amount = amount, price = share_value)

        # add amount of shares to user_shares (create row if it doesn't exist)
        row = db.execute("SELECT * FROM user_shares WHERE company_id = :company_id AND user_id = :user_id", company_id = company_id, user_id = user_id)
        if len(row) == 0:
            db.execute("INSERT INTO user_shares (user_id, company_id, amount) VALUES (:user_id, :company_id, :amount)", user_id = session["user_id"], company_id = company_id, amount = amount)
        else:
            cur_amount = row[0]["amount"]
            new_amount = cur_amount + amount
            db.execute("UPDATE user_shares SET amount = :amount WHERE company_id = :company_id and user_id = :user_id", amount = new_amount, user_id = session["user_id"], company_id = company_id)
        db.execute("UPDATE users SET cash = :cash WHERE id = :user_id", cash = cash_available - share_value * amount, user_id = user_id)

        flash("Shares bought!", "success")
        return redirect(url_for("index"))

    return render_template("buy.html")

@app.route("/history")
@login_required
def history():
    """Show history of transactions."""
    transactions = db.execute("SELECT companies.symbol as symbol, companies.name as name, transactions.amount as amount, transactions.price as price, transaction_types.type as type from transactions JOIN companies ON transactions.company_id = companies.id JOIN transaction_types ON transactions.transaction_type_id = transaction_types.id WHERE user_id = :user_id", user_id = session["user_id"])
    return render_template("history.html", transactions=transactions)

@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in."""

    # forget any user_id
    session.clear()

    # if user reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username")

        # ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password")

        # query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=request.form.get("username"))

        # ensure username exists and password is correct
        if len(rows) != 1 or not pwd_context.verify(request.form.get("password"), rows[0]["hash"]):
            return apology("invalid username and/or password")

        # remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # redirect user to home page
        flash("Logged in succesfully", "success")
        return redirect(url_for("index"))

    # else if user reached route via GET (as by clicking a link or via redirect)
    return render_template("login.html")

@app.route("/logout")
def logout():
    """Log user out."""

    # forget any user_id
    session.clear()

    # redirect user to login form
    return redirect(url_for("login"))

@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        if request.form["symbol"] == "":
            return apology(top="can't look", bottom="for nothing!")
        quote = lookup(request.form["symbol"])
        return render_template("quoted.html", quote=quote)

    return render_template("quote.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user."""
    if request.method == "POST":
        # if one of the form fields was blank, apologize
        if request.form["username"] == "" or request.form["password"] == "":
            return apology(top="FILL IN", bottom="THOSE FIELDS!!")
        rows = db.execute("SELECT * FROM users WHERE username = :username", username=request.form["username"])
        # if there is a user already with that name, apologize
        if len(rows) > 0:
            return apology(top="you can't", bottom="register again!")

        # hash the password and save user and hash to db
        hash = pwd_context.hash(request.form["password"])
        db.execute("INSERT INTO users (username, hash) VALUES (:username, :hash)", username=request.form["username"], hash=hash)
        return redirect(url_for("login"))
    else:
        return render_template("register.html")

@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock."""
    if request.method == "POST":
        # transaction types: 1 - buy, 2 - sell
        transaction_type_id = 2
        user_id = session["user_id"]
        symbol = request.form["symbol"]
        amount = int(request.form["amount"])

        quote = lookup(symbol)
        price = quote["price"]
        shares = db.execute("SELECT * FROM user_shares WHERE company_id = (SELECT id FROM companies WHERE symbol = :symbol) AND user_id = :user_id", user_id = user_id, symbol = symbol)

        if len(shares) == 0:
            flash("You don't have shares for that company", "danger")
            return render_template("sell.html")

        shares = shares[0]
        if amount > shares["amount"]:
            flash("You can't sell more shares than you own", "danger")
            return render_template("sell.html")

        db.execute("INSERT INTO transactions (transaction_type_id, user_id, company_id, amount, price) VALUES(:transaction_type_id, :user_id, :company_id, :amount, :price)", transaction_type_id = transaction_type_id, user_id = session["user_id"], company_id = shares["company_id"], amount = amount, price = price)


        benefit = amount * price
        db.execute("UPDATE user_shares SET amount = amount - :amount WHERE company_id = :company_id AND user_id = :user_id", amount = amount, company_id = shares["company_id"], user_id = user_id)
        db.execute("UPDATE users SET cash = cash + :benefit WHERE id = :user_id", benefit = benefit, user_id = user_id)

        flash("Shares sold succesfully for {}".format(usd(benefit)), "success")
        return redirect(url_for("index"))
    return render_template("sell.html")
