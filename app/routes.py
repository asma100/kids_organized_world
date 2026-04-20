from flask import render_template, url_for, flash, redirect, request
from app import app, db, bcrypt
from app.forms import (RegistrationForm, LoginForm, CreateTaskForm,
                       UpdateTaskForm, GoodActionForm, BadActionForm,
                       RewardForm, PunishmentForm, AddMoneyForm,
                       SpendMoneyForm, SavingsGoalForm, SplitForm)
from flask_login import login_user, current_user, logout_user, login_required
from app.taskMangment import create_task, get_tasksList_for_user, update_task, delete_task
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
        create_task(title=form.title.data, description=form.description.data,
                    date=form.date.data, time=form.time.data)
        flash('Task created! ✅', 'success')
        return redirect(url_for('taskList'))
    return render_template("createtask.html", form=form)


@app.route("/taskList")
@login_required
def taskList():
    user_tasks_list = get_tasksList_for_user()
    form = UpdateTaskForm()
    return render_template("taskList.html", title='Task List',
                           User_tasks_list=user_tasks_list,
                           user=current_user, form=form)


@app.route("/updatetask/<int:task_id>", methods=["GET", "POST"])
@login_required
def updatetask(task_id):
    task = Task.query.get_or_404(task_id)
    if task.user_id != current_user.id:
        flash('Not authorized.', 'danger')
        return redirect(url_for('taskList'))
    form = UpdateTaskForm()
    if form.validate_on_submit():
        update_task(task_id=task_id,
                    title=form.title.data or None,
                    description=form.description.data or None,
                    completion_status=form.completion_status.data)
        flash('Task updated!', 'success')
        return redirect(url_for('taskList'))
    form.title.data = task.title
    form.description.data = task.description
    form.completion_status.data = task.completion_status
    return render_template("taskupdate.html", form=form, task=task)


@app.route("/deletetask/<int:task_id>", methods=["POST"])
@login_required
def deletetask(task_id):
    success = delete_task(task_id)
    flash('Task deleted.' if success else 'Not found.', 'success' if success else 'danger')
    return redirect(url_for('taskList'))


@app.route("/toggle_task/<int:task_id>", methods=["POST"])
@login_required
def toggle_task(task_id):
    t = Task.query.get_or_404(task_id)
    if t.user_id != current_user.id:
        flash("Unauthorized.", "danger")
        return redirect(url_for('taskList'))
    t.completion_status = not t.completion_status
    db.session.commit()
    total_task_points(current_user.id)
    return redirect(url_for('taskList'))


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
    return render_template("edit_action.html", form=form, action=action,
                           mode='good', field_label='Points Value',
                           field_name='points_value')


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
    return render_template("edit_action.html", form=form, action=action,
                           mode='bad', field_label='Crosses Value',
                           field_name='crosses_value')


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
        if account:
            flash(f'🛍 Spent {form.amount.data:.2f}!', 'success')
        else:
            flash("Not enough spending money!", 'danger')
    return redirect(url_for('money'))


@app.route("/money/donate", methods=["POST"])
@login_required
def money_donate():
    form = SpendMoneyForm()
    if form.validate_on_submit():
        account = donate_money(current_user.id, form.amount.data, form.note.data or "")
        if account:
            flash(f'❤️ Donated {form.amount.data:.2f}!', 'success')
        else:
            flash("Not enough donation money!", 'danger')
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