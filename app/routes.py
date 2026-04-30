from datetime import date as date_type, timedelta, datetime
from flask import render_template, url_for, flash, redirect, request, session
from app import app, db, bcrypt
from app.forms import (RegistrationForm, LoginForm, CreateTaskForm,
                       UpdateTaskForm, GoodActionForm, BadActionForm,
                       RewardForm, PunishmentForm, AddMoneyForm,
                       SpendMoneyForm, SavingsGoalForm, SplitForm,
                       GoalDepositForm,
                       CreateChildForm)
from flask_login import login_user, current_user, logout_user, login_required
from app.taskManagement import (create_task, get_tasks_for_date, update_task,
                                delete_task, toggle_task_for_date, recurrence_label)
from app.pointsys import total_task_points
from app.models import User, Task, GoodAction, BadAction, Reward, Punishment
import uuid
from app.goodact import (create_good_action, get_good_actions, delete_good_action,
                         award_good_action, create_reward, get_rewards, delete_reward,
                         use_reward, PREDEFINED_REWARDS)
from app.badact import (create_bad_action, get_bad_actions, delete_bad_action,
                        assign_bad_action, create_punishment, get_punishments,
                        delete_punishment, serve_punishment, PREDEFINED_PUNISHMENTS)
from app.moneyOrganizer import (get_or_create_account, add_money, spend_money,
                                donate_money, set_category_percentages,
                                deposit_to_goal,
                                create_savings_goal, get_savings_goals,
                                get_transactions, DEFAULT_CATEGORIES)



import io
from flask import send_file
from app.omr_pdf import generate_task_sheet
from app.omr_scanner import process_scanned_sheet



from app.task_image import save_task_image, delete_task_image, allowed_image
from app.models import PresetTask, seed_presets
from app.models import CATEGORY_LABELS   # for the presets page



def _parse_date(date_str):
    """Parse a YYYY-MM-DD string; return today if invalid/missing."""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return date_type.today()


def _effective_parent_id():
    """Parent owner for shared configs like actions/rewards/punishments."""
    if current_user.role == 'parent':
        return current_user.id
    return current_user.parent_id or current_user.id


def _active_child_user():
    """Selected child for parent context, or current user if logged in as child."""
    if current_user.role != 'parent':
        return current_user

    selected_id = session.get('active_child_id')
    if not selected_id:
        return None

    return User.query.filter_by(id=selected_id, parent_id=current_user.id).first()


def _active_child_id():
    child = _active_child_user()
    return child.id if child else None


# ── AUTH ──────────────────────────────────────────────────────────────────────

@app.route("/", methods=['GET', 'POST'])
@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('parent' if current_user.role == 'parent' else 'home'))
    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(username=form.username.data,
                    email=form.email.data,
                    password=hashed_password,
                    role='parent')
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash('Your account has been created! ✅', 'success')
        return redirect(url_for('parent'))
    return render_template('register.html', form=form)


@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('parent' if current_user.role == 'parent' else 'home'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and bcrypt.check_password_hash(user.password, form.password.data):
            login_user(user, remember=form.remember.data)
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            return redirect(url_for('parent' if user.role == 'parent' else 'home'))
        flash('Login unsuccessful. Please check email and password.', 'danger')
    return render_template('login.html', form=form)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    session.pop('active_child_id', None)
    return redirect(url_for('login'))


# ── HOME ──────────────────────────────────────────────────────────────────────

@app.route("/home")
@login_required
def home():
    view_user = _active_child_user() if current_user.role == 'parent' else current_user
    if current_user.role == 'parent' and not view_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))
    return render_template("home.html", view_user=view_user)


@app.route("/parent", methods=["GET", "POST"])
@login_required
def parent():
    # Only parents may create child profiles
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    form = CreateChildForm()
    kids = User.query.filter_by(parent_id=current_user.id).all()
    selected_child_id = session.get('active_child_id')
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash('That username is already taken.', 'danger')
            return redirect(url_for('parent'))
        email = (form.email.data or '').strip()
        if not email:
            email = f"child_{uuid.uuid4().hex[:10]}@kow.local"
        if User.query.filter_by(email=email).first():
            flash('That email is already in use.', 'danger')
            return redirect(url_for('parent'))
        # Generate a random password (child won't use it unless parent sets it)
        random_pw = uuid.uuid4().hex
        hashed = bcrypt.generate_password_hash(random_pw).decode('utf-8')
        child = User(username=form.username.data,
                     email=email,
                     password=hashed,
                     role='child',
                     parent_id=current_user.id)
        db.session.add(child)
        db.session.commit()
        session['active_child_id'] = child.id
        flash(f'Child "{child.username}" created!', 'success')
        return redirect(url_for('parent'))

    selected_child = next((k for k in kids if k.id == selected_child_id), None)
    return render_template('parent.html', kids=kids, form=form, selected_child=selected_child)


@app.route('/parent/select/<int:child_id>')
@login_required
def parent_select_child(child_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    child = User.query.filter_by(id=child_id, parent_id=current_user.id).first()
    if not child:
        flash('Child profile not found.', 'danger')
        return redirect(url_for('parent'))

    session['active_child_id'] = child.id
    flash(f'Now viewing {child.username}.', 'success')
    return redirect(url_for('home'))


# ── CREATE TASK (with image) ──────────────────────────────────────────────────
 
@app.route("/createtask", methods=["GET", "POST"])
@login_required
def createtask():
    target_user = _active_child_user()
    if not target_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    form = CreateTaskForm()
    if form.validate_on_submit():
        r_days = [int(d) for d in form.recurrence_days.data] \
                 if form.recurrence_days.data else None
 
        # Handle image upload
        image_filename = None
        if form.image.data and form.image.data.filename:
            image_filename = save_task_image(form.image.data, target_user.id)
 
        task = create_task(
            title=form.title.data,
            description=form.description.data,
            date=form.date.data,
            time=form.time.data,
            recurrence_type=form.recurrence_type.data,
            recurrence_hours=form.recurrence_hours.data,
            recurrence_days=r_days,
            recurrence_end=form.recurrence_end.data,
            user_id=target_user.id,
        )
        # Save image filename to the task
        if image_filename:
            task.image_filename = image_filename
            db.session.commit()
 
        flash('Task created! ✅', 'success')
        return redirect(url_for('taskList'))
    return render_template("createtask.html", form=form)
 
@app.route("/taskList")
@login_required
def taskList():
    target_user = _active_child_user()
    if not target_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    # Date navigation: ?date=YYYY-MM-DD, defaults to today
    date_str = request.args.get('date')
    viewed_date = _parse_date(date_str)

    prev_date = viewed_date - timedelta(days=1)
    next_date = viewed_date + timedelta(days=1)
    today = date_type.today()
    is_today = (viewed_date == today)

    task_items = get_tasks_for_date(viewed_date, user_id=target_user.id)

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

# ── UPDATE TASK (with image change / remove) ──────────────────────────────────
 
@app.route("/updatetask/<int:task_id>", methods=["GET", "POST"])
@login_required
def updatetask(task_id):
    target_user = _active_child_user()
    if not target_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    task = Task.query.get_or_404(task_id)
    if task.user_id != target_user.id:
        flash('Not authorized.', 'danger')
        return redirect(url_for('taskList'))
 
    form = UpdateTaskForm()
    if form.validate_on_submit():
        r_days = [int(d) for d in form.recurrence_days.data] \
                 if form.recurrence_days.data else None
 
        # Handle image: remove, replace, or keep
        if form.remove_image.data and task.image_filename:
            delete_task_image(task.image_filename, target_user.id)
            task.image_filename = None
 
        elif form.image.data and form.image.data.filename:
            # Delete old image before saving new one
            if task.image_filename:
                delete_task_image(task.image_filename, target_user.id)
            task.image_filename = save_task_image(form.image.data, target_user.id)
 
        update_task(
            task_id=task_id,
            title=form.title.data or None,
            description=form.description.data or None,
            completion_status=form.completion_status.data,
            recurrence_type=form.recurrence_type.data,
            recurrence_hours=form.recurrence_hours.data,
            recurrence_days=r_days,
            recurrence_end=form.recurrence_end.data,
            user_id=target_user.id,
        )
        db.session.commit()
        flash('Task updated!', 'success')
        return redirect(url_for('taskList'))
 
    # Pre-fill
    form.title.data             = task.title
    form.description.data       = task.description
    form.completion_status.data = task.completion_status
    form.recurrence_type.data   = task.recurrence_type
    form.recurrence_hours.data  = task.recurrence_hours
    form.recurrence_days.data   = [str(d) for d in task.recurrence_days_list()]
    if task.recurrence_end:
        form.recurrence_end.data = task.recurrence_end.date() \
            if hasattr(task.recurrence_end, 'date') else task.recurrence_end
 
    return render_template("taskupdate.html", form=form, task=task,
                           recurrence_label=recurrence_label)
# ── DELETE TASK (also deletes image file) ─────────────────────────────────────
 
@app.route("/deletetask/<int:task_id>", methods=["POST"])
@login_required
def deletetask(task_id):
    target_user = _active_child_user()
    if not target_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    date_str = request.form.get('date', '')
    task     = Task.query.get(task_id)
 
    if task and task.user_id == target_user.id:
        # Clean up image file before deleting task record
        if task.image_filename:
            delete_task_image(task.image_filename, target_user.id)
 
    success = delete_task(task_id, user_id=target_user.id)
    flash('Task deleted.' if success else 'Not found.',
          'success' if success else 'danger')
    return redirect(url_for('taskList', date=date_str))

@app.route("/toggle_task/<int:task_id>", methods=["POST"])
@login_required
def toggle_task(task_id):
    target_user = _active_child_user()
    if not target_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    date_str = request.form.get('date', '')
    target_date = _parse_date(date_str)

    new_state = toggle_task_for_date(task_id, target_date, user_id=target_user.id)
    if new_state is None:
        flash("Unauthorized.", "danger")
    else:
        total_task_points(target_user.id)

    return redirect(url_for('taskList', date=date_str))



@app.route("/taskList/print")
@login_required
def print_task_sheet():
    """
    Generate and download a printable OMR PDF for the currently viewed date.
    URL: /taskList/print?date=YYYY-MM-DD
    """
    target_user = _active_child_user()
    if not target_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    date_str    = request.args.get('date', '')
    viewed_date = _parse_date(date_str)          # reuse helper already in routes.py
    task_items  = get_tasks_for_date(viewed_date, user_id=target_user.id)
 
    if not task_items:
        flash("No tasks on this date — nothing to print.", "warning")
        return redirect(url_for('taskList', date=date_str))
 
    pdf_bytes, sheet = generate_task_sheet(task_items, viewed_date, target_user)
 
    filename = f"tasks_{viewed_date.strftime('%Y-%m-%d')}_{target_user.username}.pdf"
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
    target_user = _active_child_user()
    if not target_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

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
        result = process_scanned_sheet(image_bytes, target_user)
 
        return render_template("scan_result.html", result=result)
 
    # GET — show upload form
    return render_template("scan_upload.html")


# ── GOOD ACTIONS ──────────────────────────────────────────────────────────────

@app.route("/goodactions")
@login_required
def goodactions():
    owner_parent_id = _effective_parent_id()
    actions = get_good_actions(owner_parent_id)
    rewards = get_rewards(owner_parent_id)
    target_user = _active_child_user()
    form = GoodActionForm()
    reward_form = RewardForm()
    return render_template("goodactions.html",
                           actions=actions, rewards=rewards,
                           form=form, reward_form=reward_form,
                           predefined_rewards=PREDEFINED_REWARDS,
                           target_user=target_user)


@app.route("/goodactions/create", methods=["POST"])
@login_required
def create_goodaction():
    if current_user.role != 'parent':
        flash('Only parents can create actions.', 'danger')
        return redirect(url_for('goodactions'))

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
    if current_user.role != 'parent':
        flash('Only parents can edit actions.', 'danger')
        return redirect(url_for('goodactions'))

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
    if current_user.role != 'parent':
        flash('Only parents can delete actions.', 'danger')
        return redirect(url_for('goodactions'))

    success = delete_good_action(action_id, current_user.id)
    flash('Deleted.' if success else 'Not found.', 'success' if success else 'danger')
    return redirect(url_for('goodactions'))


@app.route("/goodactions/award/<int:action_id>", methods=["POST"])
@login_required
def award_goodaction(action_id):
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    new_points = award_good_action(target_child_id, action_id)
    if new_points is not None:
        flash(f'🎉 Great job! You now have {new_points} points!', 'success')
    return redirect(url_for('goodactions'))


@app.route("/rewards/create", methods=["POST"])
@login_required
def create_reward_route():
    if current_user.role != 'parent':
        flash('Only parents can create rewards.', 'danger')
        return redirect(url_for('goodactions'))

    form = RewardForm()
    if form.validate_on_submit():
        create_reward(parent_id=current_user.id,
                      name=form.name.data,
                      points_threshold=form.points_threshold.data,
                      description=form.description.data,
                      points_cost=form.points_cost.data)
        flash(f'Reward "{form.name.data}" added! 🏆', 'success')
    return redirect(url_for('goodactions'))


@app.route("/rewards/use/<int:reward_id>", methods=["POST"])
@login_required
def use_reward_route(reward_id):
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    success, message = use_reward(target_child_id, reward_id)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('goodactions'))


@app.route("/rewards/delete/<int:reward_id>", methods=["POST"])
@login_required
def delete_reward_route(reward_id):
    if current_user.role != 'parent':
        flash('Only parents can delete rewards.', 'danger')
        return redirect(url_for('goodactions'))

    delete_reward(reward_id, current_user.id)
    flash('Reward removed.', 'success')
    return redirect(url_for('goodactions'))


# ── BAD ACTIONS ───────────────────────────────────────────────────────────────

@app.route("/badactions")
@login_required
def badactions():
    owner_parent_id = _effective_parent_id()
    actions = get_bad_actions(owner_parent_id)
    punishments = get_punishments(owner_parent_id)
    target_user = _active_child_user()
    form = BadActionForm()
    punishment_form = PunishmentForm()
    return render_template("badactions.html",
                           actions=actions, punishments=punishments,
                           form=form, punishment_form=punishment_form,
                           predefined_punishments=PREDEFINED_PUNISHMENTS,
                           target_user=target_user)


@app.route("/badactions/create", methods=["POST"])
@login_required
def create_badaction():
    if current_user.role != 'parent':
        flash('Only parents can create actions.', 'danger')
        return redirect(url_for('badactions'))

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
    if current_user.role != 'parent':
        flash('Only parents can edit actions.', 'danger')
        return redirect(url_for('badactions'))

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
    if current_user.role != 'parent':
        flash('Only parents can delete actions.', 'danger')
        return redirect(url_for('badactions'))

    success = delete_bad_action(action_id, current_user.id)
    flash('Deleted.' if success else 'Not found.', 'success' if success else 'danger')
    return redirect(url_for('badactions'))


@app.route("/badactions/assign/<int:action_id>", methods=["POST"])
@login_required
def assign_badaction(action_id):
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    new_crosses = assign_bad_action(target_child_id, action_id)
    if new_crosses is not None:
        flash(f'❌ Recorded. Total crosses: {new_crosses}', 'warning')
    return redirect(url_for('badactions'))


@app.route("/punishments/create", methods=["POST"])
@login_required
def create_punishment_route():
    if current_user.role != 'parent':
        flash('Only parents can create punishments.', 'danger')
        return redirect(url_for('badactions'))

    form = PunishmentForm()
    if form.validate_on_submit():
        create_punishment(parent_id=current_user.id,
                          name=form.name.data,
                          crosses_threshold=form.crosses_threshold.data,
                          description=form.description.data,
                          crosses_cost=form.crosses_cost.data)
        flash(f'Punishment "{form.name.data}" added.', 'warning')
    return redirect(url_for('badactions'))


@app.route("/punishments/serve/<int:punishment_id>", methods=["POST"])
@login_required
def serve_punishment_route(punishment_id):
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    success, message = serve_punishment(target_child_id, punishment_id)
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('badactions'))


@app.route("/punishments/delete/<int:punishment_id>", methods=["POST"])
@login_required
def delete_punishment_route(punishment_id):
    if current_user.role != 'parent':
        flash('Only parents can delete punishments.', 'danger')
        return redirect(url_for('badactions'))

    delete_punishment(punishment_id, current_user.id)
    flash('Removed.', 'success')
    return redirect(url_for('badactions'))


# ── MONEY ─────────────────────────────────────────────────────────────────────

@app.route("/money")
@login_required
def money():
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    account = get_or_create_account(target_child_id)
    goals = get_savings_goals(target_child_id)
    transactions = get_transactions(target_child_id, limit=15)
    add_form = AddMoneyForm()
    spend_form = SpendMoneyForm()
    goal_form = SavingsGoalForm()
    goal_deposit_form = GoalDepositForm()
    split_form = SplitForm()
    split_form.saving_pct.data = DEFAULT_CATEGORIES["saving"]
    split_form.spending_pct.data = DEFAULT_CATEGORIES["spending"]
    split_form.donating_pct.data = DEFAULT_CATEGORIES["donating"]

    add_form.add_mode.data = 'unassigned'
    add_form.saving_pct.data = DEFAULT_CATEGORIES["saving"]
    add_form.spending_pct.data = DEFAULT_CATEGORIES["spending"]
    add_form.donating_pct.data = DEFAULT_CATEGORIES["donating"]
    return render_template("money.html",
                           account=account, goals=goals,
                           transactions=transactions,
                           add_form=add_form, spend_form=spend_form,
                           goal_form=goal_form,
                           goal_deposit_form=goal_deposit_form,
                           split_form=split_form)


@app.route("/money/add", methods=["POST"])
@login_required
def money_add():
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    form = AddMoneyForm()
    if form.validate_on_submit():
        saving_pct = None
        spending_pct = None
        donating_pct = None

        if form.add_mode.data == 'auto_split':
            saving_pct = form.saving_pct.data
            spending_pct = form.spending_pct.data
            donating_pct = form.donating_pct.data

            if saving_pct is None and spending_pct is None and donating_pct is None:
                saving_pct = DEFAULT_CATEGORIES['saving']
                spending_pct = DEFAULT_CATEGORIES['spending']
                donating_pct = DEFAULT_CATEGORIES['donating']
            else:
                if saving_pct is None:
                    saving_pct = DEFAULT_CATEGORIES['saving']
                if spending_pct is None:
                    spending_pct = DEFAULT_CATEGORIES['spending']
                if donating_pct is None:
                    donating_pct = DEFAULT_CATEGORIES['donating']

            if (saving_pct + spending_pct + donating_pct) != 100:
                flash('Auto split must add up to 100%.', 'danger')
                return redirect(url_for('money'))

        added = add_money(target_child_id, form.amount.data, form.note.data or "")
        if not added:
            flash('Invalid amount.', 'danger')
            return redirect(url_for('money'))

        if form.add_mode.data == 'auto_split':
            set_category_percentages(target_child_id, saving_pct, spending_pct, donating_pct)
            flash('Added money and auto-split into jars! 📊', 'success')
        else:
            flash('Money added to Unassigned.', 'success')
    else:
        flash('Invalid add money values.', 'danger')

    return redirect(url_for('money'))


@app.route("/money/spend", methods=["POST"])
@login_required
def money_spend():
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    form = SpendMoneyForm()
    if form.validate_on_submit():
        account = spend_money(target_child_id, form.amount.data, form.note.data or "")
        flash(f'🛍 Spent {form.amount.data:.2f}!' if account else "Not enough spending money!", 
              'success' if account else 'danger')
    return redirect(url_for('money'))


@app.route("/money/donate", methods=["POST"])
@login_required
def money_donate():
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    form = SpendMoneyForm()
    if form.validate_on_submit():
        account = donate_money(target_child_id, form.amount.data, form.note.data or "")
        flash(f'🤝 Kindness {form.amount.data:.2f}!' if account else "Not enough kindness money!",
              'success' if account else 'danger')
    return redirect(url_for('money'))


@app.route("/money/goal/deposit/<int:goal_id>", methods=["POST"])
@login_required
def money_goal_deposit(goal_id):
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    form = GoalDepositForm()
    if form.validate_on_submit():
        goal, message = deposit_to_goal(target_child_id, goal_id, form.amount.data)
        flash(message, 'success' if goal else 'danger')
    else:
        flash('Invalid deposit amount.', 'danger')
    return redirect(url_for('money'))


@app.route("/money/split", methods=["POST"])
@login_required
def money_split():
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    form = SplitForm()
    if form.validate_on_submit():
        account = get_or_create_account(target_child_id)
        if account.unassigned_balance <= 0:
            flash('No unassigned money to sort yet.', 'warning')
            return redirect(url_for('money'))

        saving_pct = form.saving_pct.data
        spending_pct = form.spending_pct.data
        donating_pct = form.donating_pct.data

        if saving_pct is None and spending_pct is None and donating_pct is None:
            saving_pct = DEFAULT_CATEGORIES['saving']
            spending_pct = DEFAULT_CATEGORIES['spending']
            donating_pct = DEFAULT_CATEGORIES['donating']
        else:
            if saving_pct is None:
                saving_pct = DEFAULT_CATEGORIES['saving']
            if spending_pct is None:
                spending_pct = DEFAULT_CATEGORIES['spending']
            if donating_pct is None:
                donating_pct = DEFAULT_CATEGORIES['donating']

        if (saving_pct + spending_pct + donating_pct) != 100:
            flash('Split must add up to 100%.', 'danger')
            return redirect(url_for('money'))

        result = set_category_percentages(target_child_id,
                                          saving_pct,
                                          spending_pct,
                                          donating_pct)
        flash('Money sorted into the jars! 📊' if result else 'Something went wrong.',
              'success' if result else 'danger')
    else:
        flash('Invalid split values.', 'danger')
    return redirect(url_for('money'))


@app.route("/money/goal", methods=["POST"])
@login_required
def money_goal():
    target_child_id = _active_child_id()
    if target_child_id is None:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))

    form = SavingsGoalForm()
    if form.validate_on_submit():
        create_savings_goal(target_child_id, form.name.data,
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
    target_user = _active_child_user()
    if not target_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))
 
    if request.method == "POST" and 'sheet_image' in request.files:
        image_bytes = request.files['sheet_image'].read()
        raw_info    = debug_scan_image(image_bytes, target_user)
 
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


    
# ── PRESET TASKS PAGE ─────────────────────────────────────────────────────────
 
@app.route("/presets")
@login_required
def presets():
    """
    Gallery of common ready-made tasks. Parents click + Add to create
    a copy in their task list with sensible defaults.
    """
    # Group presets by category
    from collections import defaultdict
    all_presets = PresetTask.query.order_by(PresetTask.category, PresetTask.id).all()
 
    grouped = defaultdict(list)
    for p in all_presets:
        grouped[p.category].append(p)
 
    # Build ordered list of (category_key, label_tuple, presets_list)
    categories = []
    for key, label_tuple in CATEGORY_LABELS.items():
        if grouped[key]:
            categories.append((key, label_tuple, grouped[key]))
 
    # Any preset category not in CATEGORY_LABELS goes to 'other'
    other = [p for p in all_presets if p.category not in CATEGORY_LABELS]
    if other:
        categories.append(('other', ('📌', 'Other', 'أخرى'), other))
 
    return render_template("presets.html", categories=categories)
 
 
# ── ADD PRESET TO TASK LIST ───────────────────────────────────────────────────
 
@app.route("/presets/add/<int:preset_id>", methods=["POST"])
@login_required
def add_preset_task(preset_id):
    """
    One-click add: copies a preset into the user's task list for today,
    using the preset's default recurrence.
    Parent can edit date/time afterwards via the normal edit route.
    """
    from datetime import date as date_type, time as time_type
    import os, shutil

    target_user = _active_child_user()
    if not target_user:
        flash('Select a child profile first.', 'warning')
        return redirect(url_for('parent'))
 
    preset = PresetTask.query.get_or_404(preset_id)
    today  = date_type.today()
 
    # Copy the preset's bundled image into the user's task_images folder
    image_filename = None
    if preset.image_filename:
        src = os.path.join(
            app.root_path, 'static', 'preset_images', preset.image_filename
        )
        if os.path.exists(src):
            from app.task_image import _user_folder
            import uuid
            dst_folder = _user_folder(target_user.id)
            dst_name   = f"{uuid.uuid4().hex}.png"
            dst        = os.path.join(dst_folder, dst_name)
            shutil.copy2(src, dst)
            image_filename = dst_name
 
    # Create the task using the preset title + description
    # Use Arabic title if user's locale is Arabic (simple heuristic: check DB)
    title       = preset.title
    description = preset.description
 
    task = create_task(
        title=title,
        description=description,
        date=today,
        time=time_type(8, 0),              # default 08:00, parent can change
        recurrence_type=preset.default_recurrence,
        user_id=target_user.id,
    )
    if image_filename:
        task.image_filename = image_filename
        db.session.commit()
 
    flash(f'{preset.emoji} "{preset.title}" added to your task list!', 'success')
    return redirect(url_for('presets'))