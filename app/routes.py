from datetime import date as date_type, timedelta, datetime
from flask import render_template, url_for, flash, redirect, request
from app import app, db, bcrypt
from app.forms import (RegistrationForm, LoginForm, CreateTaskForm,
                       UpdateTaskForm, GoodActionForm, BadActionForm,
                       RewardForm, PunishmentForm, AddMoneyForm,
                       SpendMoneyForm, SavingsGoalForm, SplitForm)
from flask_login import login_user, current_user, logout_user, login_required
from app.taskManagement import (create_task, get_tasks_for_date, update_task,
                                delete_task, toggle_task_for_date, recurrence_label)
from app.pointsys import total_task_points
from app.models import User, Task, GoodAction, BadAction, Reward, Punishment
from app.goodact import (create_good_action, get_good_actions, delete_good_action,
                         award_good_action, create_reward, get_rewards, delete_reward,
                         PREDEFINED_REWARDS)
from app.badact import (create_bad_action, get_bad_actions, delete_bad_action,
                        assign_bad_action, create_punishment, get_punishments,
                        delete_punishment, PREDEFINED_PUNISHMENTS)
from app.moneyOrganizer import (get_or_create_account, add_money, spend_money,
                                donate_money, set_category_percentages,
                                create_savings_goal, get_savings_goals,
                                get_transactions)



import io
from flask import send_file
from app.omr_pdf import generate_task_sheet
from app.omr_scanner import process_scanned_sheet



def _parse_date(date_str):
    """Parse a YYYY-MM-DD string; return today if invalid/missing."""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return date_type.today()


# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.route("/", methods=['GET', 'POST'])
@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(username=form.username.data, email=form.email.data,
                    password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('Account created! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', title='Register', form=form)


@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('home'))
        flash('Login unsuccessful. Please check email and password.', 'danger')
    return render_template('login.html', title='Login', form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# ── HOME ──────────────────────────────────────────────────────────────────────

@app.route("/home")
@login_required
def home():
    return render_template("home.html")


# ── TASKS ─────────────────────────────────────────────────────────────────────

@app.route("/createtask", methods=["GET", "POST"])
@login_required
def createtask():
    form = CreateTaskForm()
    if form.validate_on_submit():
        # Build recurrence_days list from the multi-select (list of strings '0'..'6')
        r_days = [int(d) for d in form.recurrence_days.data] if form.recurrence_days.data else None

        create_task(
            title=form.title.data,
            description=form.description.data,
            date=form.date.data,
            time=form.time.data,
            recurrence_type=form.recurrence_type.data,
            recurrence_hours=form.recurrence_hours.data,
            recurrence_days=r_days,
            recurrence_end=form.recurrence_end.data,
        )
        flash('Task created! ✅', 'success')
        return redirect(url_for('taskList'))
    return render_template("createtask.html", form=form)


@app.route("/taskList")
@login_required
def taskList():
    # Date navigation: ?date=YYYY-MM-DD, defaults to today
    date_str = request.args.get('date')
    viewed_date = _parse_date(date_str)

    prev_date = viewed_date - timedelta(days=1)
    next_date = viewed_date + timedelta(days=1)
    today = date_type.today()
    is_today = (viewed_date == today)

    task_items = get_tasks_for_date(viewed_date)

    # A plain form just for CSRF tokens in toggle/delete sub-forms
    form = UpdateTaskForm()

    return render_template("taskList.html",
                           task_items=task_items,
                           viewed_date=viewed_date,
                           prev_date=prev_date,
                           next_date=next_date,
                           today=today,
                           is_today=is_today,
                           form=form,
                           recurrence_label=recurrence_label)



@app.route("/updatetask/<int:task_id>", methods=["GET", "POST"])
@login_required
def updatetask(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id != current_user.id:
        flash('Not authorized.', 'danger')
        return redirect(url_for('taskList'))

    form = UpdateTaskForm()
    if form.validate_on_submit():
        r_days = [int(d) for d in form.recurrence_days.data] if form.recurrence_days.data else None
        update_task(
            task_id=task_id,
            title=form.title.data or None,
            description=form.description.data or None,
            completion_status=form.completion_status.data,
            recurrence_type=form.recurrence_type.data,
            recurrence_hours=form.recurrence_hours.data,
            recurrence_days=r_days,
            recurrence_end=form.recurrence_end.data,
        )
        flash('Task updated!', 'success')
        return redirect(url_for('taskList'))

    # Pre-fill
    form.title.data = task.title
    form.description.data = task.description
    form.completion_status.data = task.completion_status
    form.recurrence_type.data = task.recurrence_type
    form.recurrence_hours.data = task.recurrence_hours
    form.recurrence_days.data = [str(d) for d in task.recurrence_days_list()]
    if task.recurrence_end:
        form.recurrence_end.data = task.recurrence_end.date() if hasattr(task.recurrence_end, 'date') else task.recurrence_end

    return render_template("taskupdate.html", form=form, task=task,
                           recurrence_label=recurrence_label)


@app.route("/deletetask/<int:task_id>", methods=["POST"])
@login_required
def deletetask(task_id):
    # Pass date back so we stay on the same day after deleting
    date_str = request.form.get('date', '')
    success = delete_task(task_id)
    flash('Task deleted.' if success else 'Not found.', 'success' if success else 'danger')
    return redirect(url_for('taskList', date=date_str))


@app.route("/toggle_task/<int:task_id>", methods=["POST"])
@login_required
def toggle_task(task_id):
    date_str = request.form.get('date', '')
    target_date = _parse_date(date_str)

    new_state = toggle_task_for_date(task_id, target_date)
    if new_state is None:
        flash("Unauthorized.", "danger")
    else:
        total_task_points(current_user.id)

    return redirect(url_for('taskList', date=date_str))



@app.route("/taskList/print")
@login_required
def print_task_sheet():
    """
    Generate and download a printable OMR PDF for the currently viewed date.
    URL: /taskList/print?date=YYYY-MM-DD
    """
    date_str    = request.args.get('date', '')
    viewed_date = _parse_date(date_str)          # reuse helper already in routes.py
    task_items  = get_tasks_for_date(viewed_date)
 
    if not task_items:
        flash("No tasks on this date — nothing to print.", "warning")
        return redirect(url_for('taskList', date=date_str))
 
    pdf_bytes, sheet = generate_task_sheet(task_items, viewed_date, current_user)
 
    filename = f"tasks_{viewed_date.strftime('%Y-%m-%d')}_{current_user.username}.pdf"
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename
    )
 
 
@app.route("/scan", methods=["GET", "POST"])
@login_required
def scan_sheet():
    """
    GET  → show the upload form
    POST → receive the scanned image, run OMR, update tasks, show results
    """
    if request.method == "POST":
        if 'sheet_image' not in request.files:
            flash("No file uploaded.", "danger")
            return redirect(url_for('scan_sheet'))
 
        file = request.files['sheet_image']
        if file.filename == '':
            flash("No file selected.", "danger")
            return redirect(url_for('scan_sheet'))
 
        allowed = {'png', 'jpg', 'jpeg', 'webp', 'bmp', 'tiff', 'tif'}
        ext = file.filename.rsplit('.', 1)[-1].lower()
        if ext not in allowed:
            flash(f"Unsupported file type '.{ext}'. Upload a photo or scan (JPG/PNG).", "danger")
            return redirect(url_for('scan_sheet'))
 
        image_bytes = file.read()
        result = process_scanned_sheet(image_bytes, current_user)
 
        return render_template("scan_result.html", result=result)
 
    # GET — show upload form
    return render_template("scan_upload.html")


# ── GOOD ACTIONS ──────────────────────────────────────────────────────────────

@app.route("/goodactions")
@login_required
def goodactions():
    actions = get_good_actions(current_user.id)
    rewards = get_rewards(current_user.id)
    form = GoodActionForm()
    reward_form = RewardForm()
    return render_template("goodactions.html",
                           actions=actions, rewards=rewards,
                           form=form, reward_form=reward_form,
                           predefined_rewards=PREDEFINED_REWARDS)


@app.route("/goodactions/create", methods=["POST"])
@login_required
def create_goodaction():
    form = GoodActionForm()
    if form.validate_on_submit():
        create_good_action(parent_id=current_user.id,
                           name=form.name.data,
                           points_value=form.points_value.data,
                           description=form.description.data)
        flash(f'Good action "{form.name.data}" created! ⭐', 'success')
    return redirect(url_for('goodactions'))


@app.route("/goodactions/edit/<int:action_id>", methods=["GET", "POST"])
@login_required
def edit_goodaction(action_id):
    action = GoodAction.query.get_or_404(action_id)
    if action.parent_id != current_user.id:
        flash("Not authorized.", "danger")
        return redirect(url_for('goodactions'))
    form = GoodActionForm()
    if form.validate_on_submit():
        action.name = form.name.data
        action.description = form.description.data
        action.points_value = form.points_value.data
        db.session.commit()
        flash('Updated!', 'success')
        return redirect(url_for('goodactions'))
    form.name.data = action.name
    form.description.data = action.description
    form.points_value.data = action.points_value
    return render_template("edit_action.html", form=form, action=action, mode='good')


@app.route("/goodactions/delete/<int:action_id>", methods=["POST"])
@login_required
def delete_goodaction(action_id):
    success = delete_good_action(action_id, current_user.id)
    flash('Deleted.' if success else 'Not found.', 'success' if success else 'danger')
    return redirect(url_for('goodactions'))


@app.route("/goodactions/award/<int:action_id>", methods=["POST"])
@login_required
def award_goodaction(action_id):
    new_points = award_good_action(current_user.id, action_id)
    if new_points is not None:
        flash(f'🎉 Great job! You now have {new_points} points!', 'success')
    return redirect(url_for('goodactions'))


@app.route("/rewards/create", methods=["POST"])
@login_required
def create_reward_route():
    form = RewardForm()
    if form.validate_on_submit():
        create_reward(parent_id=current_user.id,
                      name=form.name.data,
                      points_threshold=form.points_threshold.data,
                      description=form.description.data)
        flash(f'Reward "{form.name.data}" added! 🏆', 'success')
    return redirect(url_for('goodactions'))


@app.route("/rewards/delete/<int:reward_id>", methods=["POST"])
@login_required
def delete_reward_route(reward_id):
    delete_reward(reward_id, current_user.id)
    flash('Reward removed.', 'success')
    return redirect(url_for('goodactions'))


# ── BAD ACTIONS ───────────────────────────────────────────────────────────────

@app.route("/badactions")
@login_required
def badactions():
    actions = get_bad_actions(current_user.id)
    punishments = get_punishments(current_user.id)
    form = BadActionForm()
    punishment_form = PunishmentForm()
    return render_template("badactions.html",
                           actions=actions, punishments=punishments,
                           form=form, punishment_form=punishment_form,
                           predefined_punishments=PREDEFINED_PUNISHMENTS)


@app.route("/badactions/create", methods=["POST"])
@login_required
def create_badaction():
    form = BadActionForm()
    if form.validate_on_submit():
        create_bad_action(parent_id=current_user.id,
                          name=form.name.data,
                          crosses_value=form.crosses_value.data,
                          description=form.description.data)
        flash(f'Bad action "{form.name.data}" added.', 'warning')
    return redirect(url_for('badactions'))


@app.route("/badactions/edit/<int:action_id>", methods=["GET", "POST"])
@login_required
def edit_badaction(action_id):
    action = BadAction.query.get_or_404(action_id)
    if action.parent_id != current_user.id:
        flash("Not authorized.", "danger")
        return redirect(url_for('badactions'))
    form = BadActionForm()
    if form.validate_on_submit():
        action.name = form.name.data
        action.description = form.description.data
        action.crosses_value = form.crosses_value.data
        db.session.commit()
        flash('Updated!', 'success')
        return redirect(url_for('badactions'))
    form.name.data = action.name
    form.description.data = action.description
    form.crosses_value.data = action.crosses_value
    return render_template("edit_action.html", form=form, action=action, mode='bad')


@app.route("/badactions/delete/<int:action_id>", methods=["POST"])
@login_required
def delete_badaction(action_id):
    success = delete_bad_action(action_id, current_user.id)
    flash('Deleted.' if success else 'Not found.', 'success' if success else 'danger')
    return redirect(url_for('badactions'))


@app.route("/badactions/assign/<int:action_id>", methods=["POST"])
@login_required
def assign_badaction(action_id):
    new_crosses = assign_bad_action(current_user.id, action_id)
    if new_crosses is not None:
        flash(f'❌ Recorded. Total crosses: {new_crosses}', 'warning')
    return redirect(url_for('badactions'))


@app.route("/punishments/create", methods=["POST"])
@login_required
def create_punishment_route():
    form = PunishmentForm()
    if form.validate_on_submit():
        create_punishment(parent_id=current_user.id,
                          name=form.name.data,
                          crosses_threshold=form.crosses_threshold.data,
                          description=form.description.data)
        flash(f'Punishment "{form.name.data}" added.', 'warning')
    return redirect(url_for('badactions'))


@app.route("/punishments/delete/<int:punishment_id>", methods=["POST"])
@login_required
def delete_punishment_route(punishment_id):
    delete_punishment(punishment_id, current_user.id)
    flash('Removed.', 'success')
    return redirect(url_for('badactions'))


# ── MONEY ─────────────────────────────────────────────────────────────────────

@app.route("/money")
@login_required
def money():
    account = get_or_create_account(current_user.id)
    goals = get_savings_goals(current_user.id)
    transactions = get_transactions(current_user.id, limit=15)
    add_form = AddMoneyForm()
    spend_form = SpendMoneyForm()
    goal_form = SavingsGoalForm()
    split_form = SplitForm()
    split_form.saving_pct.data = account.saving_pct
    split_form.spending_pct.data = account.spending_pct
    split_form.donating_pct.data = account.donating_pct
    return render_template("money.html",
                           account=account, goals=goals,
                           transactions=transactions,
                           add_form=add_form, spend_form=spend_form,
                           goal_form=goal_form, split_form=split_form)


@app.route("/money/add", methods=["POST"])
@login_required
def money_add():
    form = AddMoneyForm()
    if form.validate_on_submit():
        account = add_money(current_user.id, form.amount.data, form.note.data or "")
        if account:
            flash(f'💰 Added {form.amount.data:.2f}! Total: {account.total_balance:.2f}', 'success')
        else:
            flash('Invalid amount.', 'danger')
    return redirect(url_for('money'))


@app.route("/money/spend", methods=["POST"])
@login_required
def money_spend():
    form = SpendMoneyForm()
    if form.validate_on_submit():
        account = spend_money(current_user.id, form.amount.data, form.note.data or "")
        flash(f'🛍 Spent {form.amount.data:.2f}!' if account else "Not enough spending money!", 
              'success' if account else 'danger')
    return redirect(url_for('money'))


@app.route("/money/donate", methods=["POST"])
@login_required
def money_donate():
    form = SpendMoneyForm()
    if form.validate_on_submit():
        account = donate_money(current_user.id, form.amount.data, form.note.data or "")
        flash(f'❤️ Donated {form.amount.data:.2f}!' if account else "Not enough donation money!",
              'success' if account else 'danger')
    return redirect(url_for('money'))


@app.route("/money/split", methods=["POST"])
@login_required
def money_split():
    form = SplitForm()
    if form.validate_on_submit():
        result = set_category_percentages(current_user.id,
                                          form.saving_pct.data,
                                          form.spending_pct.data,
                                          form.donating_pct.data)
        flash('Split updated! 📊' if result else 'Must add up to 100!',
              'success' if result else 'danger')
    return redirect(url_for('money'))


@app.route("/money/goal", methods=["POST"])
@login_required
def money_goal():
    form = SavingsGoalForm()
    if form.validate_on_submit():
        create_savings_goal(current_user.id, form.name.data,
                            form.target_amount.data,
                            form.reward_description.data or "")
        flash(f'🎯 Goal "{form.name.data}" set!', 'success')
    return redirect(url_for('money'))

import base64
 
 
@app.route("/scan/debug", methods=["GET", "POST"])
@login_required
def scan_debug():
    """
    Developer diagnostic page.
    Uploads an image, runs the full detection pipeline, shows annotated result.
    Does NOT modify any task data.
    """
    from app.omr_scanner import debug_scan_image, DARK_FRACTION_REQUIRED
    info = None
 
    if request.method == "POST" and 'sheet_image' in request.files:
        image_bytes = request.files['sheet_image'].read()
        raw_info    = debug_scan_image(image_bytes, current_user)
 
        # Convert annotated JPEG bytes → base64 string for inline <img src>
        if raw_info.get('annotated_jpeg'):
            raw_info['annotated_jpeg_b64'] = base64.b64encode(
                raw_info['annotated_jpeg']
            ).decode('utf-8')
        else:
            raw_info['annotated_jpeg_b64'] = None
 
        raw_info['threshold'] = DARK_FRACTION_REQUIRED
        info = raw_info
 
    return render_template("scan_debug.html", info=info)