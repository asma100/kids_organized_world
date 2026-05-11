from datetime import date as date_type, timedelta, datetime
import calendar as pycal
from flask import render_template, url_for, flash, redirect, request, session, jsonify, current_app
from app import app, db, bcrypt, oauth, csrf
from app.forms import (RegistrationForm, LoginForm, CreateTaskForm,
                       UpdateTaskForm, GoodActionForm, BadActionForm,
                       RewardForm, PunishmentForm, AddMoneyForm,
                       SpendMoneyForm, SavingsGoalForm, SplitForm,
                       GoalDepositForm,
                       CreateChildForm,
                       ParentBulkCreateTaskForm,
                       TurnGroupForm, TurnAddMemberForm,
                       TurnSettingsForm, TurnPauseForm, TurnActionForm,
                       TurnSkipForm, TurnSwapRequestForm, TurnSharedJoinForm,
                       TurnNudgeForm,
                       TurnTradeForm, TurnWeekdayRuleForm, TurnCalSettingsForm)
from flask_login import login_user, current_user, logout_user, login_required
from app.taskManagement import (create_task, get_tasks_for_date, update_task,
                                delete_task, toggle_task_for_date, recurrence_label)
from app.pointsys import total_task_points
from app.models import (User, Task, GoodAction, BadAction, Reward, Punishment,
                        TurnGroup, TurnGroupMember, TurnDailyUsage, TurnDayState,
                        TurnSwapRequest, TurnWeekdayRule, TurnAuditLog)
from app.turn import (
    turn_day_key,
    get_or_init_turn_state,
    queue_for_group,
    auto_advance_interval_seconds,
    advance_turn,
    skip_turn,
    request_swap,
    resolve_swap,
    join_shared_turn,
    nudge_current_child,
    execute_point_trade,
    calendar_owner_for_day,
    get_audit_log,
    get_group_members,
    check_grace_warning,
    start_turn_session,
    pause_turn_session,
    get_session_view,
)
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


@app.route('/login/google')
def login_google():
    configured_uri = app.config.get('GOOGLE_REDIRECT_URI')
    current_uri = url_for('authorize_google', _external=True)
    redirect_uri = configured_uri if configured_uri and configured_uri.startswith(request.host_url) else current_uri
    return oauth.google.authorize_redirect(redirect_uri)


@app.route('/authorize/google')
def authorize_google():
    token = oauth.google.authorize_access_token()
    user_info = oauth.google.get('https://www.googleapis.com/oauth2/v2/userinfo').json()
    email = user_info.get('email')
    name = user_info.get('name', email.split('@')[0] if email else 'Google User')

    if not email:
        flash('Google login failed: no email returned.', 'danger')
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        # Create new user if not exists
        hashed = bcrypt.generate_password_hash(uuid.uuid4().hex).decode('utf-8')
        user = User(username=name, email=email, password=hashed, role='parent')
        db.session.add(user)
        db.session.commit()

    login_user(user)
    return redirect(url_for('home'))


def _get_token_auth_user():
    auth_header = request.headers.get('Authorization', '')
    if not auth_header or not auth_header.lower().startswith('bearer '):
        return None

    token = auth_header.split(' ', 1)[1]
    return User.verify_auth_token(token)


@csrf.exempt
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'success': False, 'message': 'Email and password are required.'}), 400

    user = User.query.filter_by(email=email).first()
    if user and bcrypt.check_password_hash(user.password, password):
        token = user.get_auth_token()
        return jsonify({
            'success': True,
            'id': user.id,
            'token': token,
            'role': user.role,
            'username': user.username,
            'email': user.email,
            'points': user.points,
            'crosses': user.crosses,
        }), 200

    return jsonify({'success': False, 'message': 'Invalid email or password.'}), 401


@csrf.exempt
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    username = (data.get('username') or '').strip()
    parent_id = data.get('parent_id')
    role = (data.get('role') or '').strip().lower()

    if parent_id in ('', None):
        parent_id = None
    else:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'Parent id must be numeric.'}), 400

    if not email or not password or not username:
        return jsonify({'success': False, 'message': 'Email, password, and username are required.'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already exists.'}), 409

    if parent_id is not None:
        parent = User.query.filter_by(id=parent_id, role='parent').first()
        if not parent:
            return jsonify({'success': False, 'message': 'Parent account not found.'}), 404
        if role and role != 'child':
            return jsonify({'success': False, 'message': 'Child accounts must use role child.'}), 400
        role = 'child'
    else:
        role = 'parent'

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    user = User(username=username, email=email, password=hashed_password, role=role, parent_id=parent_id)
    db.session.add(user)
    db.session.commit()

    token = user.get_auth_token()
    return jsonify({
        'success': True,
        'id': user.id,
        'token': token,
        'role': user.role,
        'username': user.username,
        'email': user.email,
        'parent_id': user.parent_id,
        'points': user.points,
        'crosses': user.crosses,
    }), 201


@csrf.exempt
@app.route('/api/user')
def api_user():
    user = _get_token_auth_user()
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    return jsonify({
        'success': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'role': user.role,
            'parent_id': user.parent_id,
            'points': user.points,
            'crosses': user.crosses,
        }
    }), 200


@csrf.exempt
@app.route('/api/kids')
def api_kids():
    user = _get_token_auth_user()
    if not user:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    if user.role != 'parent':
        return jsonify({'success': False, 'message': 'Only parents can view kids.'}), 403

    kids = User.query.filter_by(parent_id=user.id, role='child').order_by(User.username.asc()).all()
    return jsonify({
        'success': True,
        'kids': [
            {
                'id': kid.id,
                'username': kid.username,
                'email': kid.email,
                'points': kid.points,
                'crosses': kid.crosses,
            }
            for kid in kids
        ]
    }), 200


@csrf.exempt
@app.route('/api/web_session', methods=['GET'])
def api_web_session():
    """Bridge: convert Bearer token auth into a normal Flask login session.

    This exists so the mobile app can open the existing HTML pages (taskList,
    goodactions, badactions, money) inside a WebView.

    Query params:
      - next: a relative path like /taskList
      - child_id: optional; if the authenticated user is a parent, sets
        session['active_child_id'] for that child.
    """
    user = _get_token_auth_user()
    if not user:
        return redirect(url_for('login'))

    login_user(user)

    child_id = request.args.get('child_id')
    if user.role == 'parent' and child_id:
        try:
            child_id_int = int(child_id)
        except (TypeError, ValueError):
            child_id_int = None

        if child_id_int is not None:
            child = User.query.filter_by(
                id=child_id_int,
                parent_id=user.id,
                role='child',
            ).first()
            if child:
                session['active_child_id'] = child.id

    next_path = request.args.get('next', '/home')
    if not isinstance(next_path, str) or not next_path.startswith('/') or next_path.startswith('//'):
        next_path = '/home'

    allowed_paths = {
        '/home',
        '/parent',
        '/taskList',
        '/goodactions',
        '/badactions',
        '/money',
    }
    if next_path not in allowed_paths:
        next_path = '/home'

    return redirect(next_path)


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
        if User.query.filter_by(parent_id=current_user.id, role='child', username=form.username.data).first():
            flash('That username is already taken in your family.', 'danger')
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


@app.route("/parent/create_tasks", methods=["GET", "POST"])
@login_required
def parent_create_tasks():
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    task_form = ParentBulkCreateTaskForm()
    kids = User.query.filter_by(parent_id=current_user.id, role='child').order_by(User.username.asc()).all()
    task_form.child_ids.choices = [(k.id, k.username) for k in kids]

    if request.method == 'GET':
        return render_template('parent_create_tasks.html', task_form=task_form, kids=kids)

    if not task_form.validate_on_submit():
        flash('Could not create task. Please check the form.', 'danger')
        return redirect(url_for('parent_create_tasks'))

    target_ids = [k.id for k in kids] if task_form.all_kids.data else list(task_form.child_ids.data or [])

    r_days = [int(d) for d in (task_form.recurrence_days.data or [])] if task_form.recurrence_type.data == 'weekly' else None

    created = 0
    for uid in target_ids:
        create_task(
            title=task_form.title.data,
            description=task_form.description.data,
            date=task_form.date.data,
            time=task_form.time.data,
            recurrence_type=task_form.recurrence_type.data,
            recurrence_hours=task_form.recurrence_hours.data,
            recurrence_interval_days=task_form.recurrence_interval_days.data,
            recurrence_days=r_days,
            recurrence_monthly_ordinal=task_form.recurrence_monthly_ordinal.data,
            recurrence_monthly_weekday=task_form.recurrence_monthly_weekday.data,
            recurrence_end=task_form.recurrence_end.data,
            user_id=uid,
        )
        created += 1

    flash(f'Task created for {created} kid(s)! ✅', 'success')
    return redirect(url_for('parent_create_tasks'))


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


# ── TURN MANAGEMENT (MVP) ─────────────────────────────────────────────────────


@app.route("/turns", methods=["GET", "POST"])
@login_required
def turns():
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    day = turn_day_key()
    group_form = TurnGroupForm()

    if group_form.validate_on_submit():
        category = (request.form.get('category') or 'clock').strip().lower()
        group = TurnGroup(
            parent_id=current_user.id,
            name=group_form.name.data,
            category=category,
            turn_duration_min=group_form.turn_duration_min.data or 30,
            daily_quota_min=group_form.daily_quota_min.data or 180,
        )
        db.session.add(group)
        db.session.commit()
        flash('Turn group created!', 'success')
        return redirect(url_for('turns', group_id=group.id))

    groups = TurnGroup.query.filter_by(parent_id=current_user.id).order_by(TurnGroup.created_at.desc()).all()

    selected_group_id = request.args.get('group_id', type=int)
    selected_group = None
    add_member_form = None
    queue_data = None
    session_view = None

    # Calendar view context
    cal_owner = None
    weekday_rules = []
    cal_month_weeks = None
    cal_month_legend = None
    cal_month_label = None

    # Actions/log context
    pending_swaps = []
    audit_log = []

    start_form = None
    next_form = None
    skip_form = None
    swap_form = None
    join_form = None
    nudge_form = None
    trade_form = None
    cal_form = None
    wd_form = None

    if selected_group_id:
        selected_group = TurnGroup.query.filter_by(id=selected_group_id, parent_id=current_user.id).first()

    if selected_group:
        add_member_form = TurnAddMemberForm()
        kids = User.query.filter_by(parent_id=current_user.id, role='child').order_by(User.username.asc()).all()
        existing = set(m.child_id for m in TurnGroupMember.query.filter_by(group_id=selected_group.id).all())
        choices = [(k.id, k.username) for k in kids if k.id not in existing]
        if not choices:
            choices = [(0, 'All kids already added')]
        add_member_form.child_id.choices = choices

        category = (selected_group.category or 'clock').lower()
        if category == 'calendar':
            cal_owner = calendar_owner_for_day(selected_group, day)
            weekday_rules = TurnWeekdayRule.query.filter_by(group_id=selected_group.id).all()

            # Month ownership view (visual calendar)
            members = get_group_members(selected_group)
            member_ids = [m.child_id for m in members]
            users_by_id = {}
            if member_ids:
                users = User.query.filter(User.id.in_(member_ids)).all()
                users_by_id = {u.id: u for u in users}

            palette = ['--mint', '--peach', '--lavender', '--sun', '--sky', '--grass', '--coral']
            color_by_child = {cid: palette[i % len(palette)] for i, cid in enumerate(member_ids)}

            rules_by_weekday = {r.weekday: r.child_id for r in weekday_rules}

            def _days_since_epoch(d: date_type) -> int:
                return (d - date_type(1970, 1, 1)).days

            year, month = day.year, day.month
            cal_month_label = f"{pycal.month_name[month]} {year}"
            cal = pycal.Calendar(firstweekday=0)  # Monday
            weeks = []
            for week in cal.monthdatescalendar(year, month):
                cells = []
                for d in week:
                    in_month = d.month == month
                    owner_id = None
                    if in_month and not bool(selected_group.cal_paused) and members:
                        mode = (selected_group.cal_mode or 'n_day')
                        if mode == 'weekday':
                            owner_id = rules_by_weekday.get(d.weekday())
                        elif mode == 'n_day':
                            n = int(selected_group.cal_n_days or 1)
                            idx = (_days_since_epoch(d) // max(n, 1)) % len(members)
                            owner_id = members[idx].child_id
                        elif mode == 'cyclical':
                            day_of_year = d.timetuple().tm_yday
                            idx = day_of_year % len(members)
                            owner_id = members[idx].child_id

                    owner = users_by_id.get(owner_id) if owner_id else None
                    cells.append({
                        'date': d,
                        'in_month': in_month,
                        'owner': owner,
                        'color_var': color_by_child.get(owner_id),
                        'is_today': d == day,
                    })
                weeks.append(cells)
            cal_month_weeks = weeks

            cal_month_legend = []
            for cid in member_ids:
                u = users_by_id.get(cid)
                if u:
                    cal_month_legend.append({'child': u, 'color_var': color_by_child.get(cid)})
        else:
            queue_data = queue_for_group(selected_group, day)

        session_view = get_session_view(selected_group, day) if category == 'clock' else None

        pending_swaps = TurnSwapRequest.query.filter_by(
            group_id=selected_group.id, day=day, status='pending'
        ).all()
        audit_log = get_audit_log(selected_group.id, day=day, limit=30)

        start_form = TurnActionForm()
        next_form = TurnActionForm()

        # Actions/forms
        all_kid_choices = [(k.id, k.username) for k in kids]
        members = get_group_members(selected_group)
        member_choices = [(m.child_id, (User.query.get(m.child_id).username if User.query.get(m.child_id) else str(m.child_id))) for m in members]

        skip_form = TurnSkipForm()
        skip_form.child_id.choices = member_choices or all_kid_choices

        swap_form = TurnSwapRequestForm()
        swap_form.requester_id.choices = all_kid_choices
        swap_form.target_id.choices = all_kid_choices

        join_form = TurnSharedJoinForm()
        join_form.child_id.choices = all_kid_choices

        nudge_form = TurnNudgeForm()

        trade_form = TurnTradeForm()
        trade_form.giver_id.choices = all_kid_choices
        trade_form.receiver_id.choices = all_kid_choices

        cal_form = TurnCalSettingsForm()
        cal_form.cal_mode.data = selected_group.cal_mode
        cal_form.cal_n_days.data = selected_group.cal_n_days
        cal_form.cal_paused.data = bool(selected_group.cal_paused)

        wd_form = TurnWeekdayRuleForm()
        wd_form.child_id.choices = all_kid_choices

        settings_form = TurnSettingsForm()
        settings_form.selection_mode.data = selected_group.selection_mode
        settings_form.auto_advance_enabled.data = bool(selected_group.auto_advance_enabled)
        settings_form.auto_advance_value.data = selected_group.auto_advance_value
        settings_form.auto_advance_unit.data = selected_group.auto_advance_unit
        settings_form.grace_period_sec.data = selected_group.grace_period_sec
        settings_form.deduct_overrun.data = bool(selected_group.deduct_overrun)

        pause_form = TurnPauseForm()
        pause_form.submit.label.text = 'Resume' if selected_group.auto_advance_paused else 'Pause'
        auto_seconds = auto_advance_interval_seconds(selected_group)
    else:
        settings_form = None
        pause_form = None
        auto_seconds = None
        session_view = None
        start_form = None
        next_form = None

    return render_template(
        'turns.html',
        groups=groups,
        selected_group=selected_group,
        group_form=group_form,
        add_member_form=add_member_form,
        settings_form=settings_form,
        pause_form=pause_form,
        start_form=start_form,
        next_form=next_form,
        session_view=session_view,
        queue_data=queue_data,
        day=day,
        auto_seconds=auto_seconds,
        cal_owner=cal_owner,
        weekday_rules=weekday_rules,
        cal_month_weeks=cal_month_weeks,
        cal_month_legend=cal_month_legend,
        cal_month_label=cal_month_label,
        pending_swaps=pending_swaps,
        audit_log=audit_log,
        skip_form=skip_form,
        swap_form=swap_form,
        join_form=join_form,
        nudge_form=nudge_form,
        trade_form=trade_form,
        cal_form=cal_form,
        wd_form=wd_form,
    )


@app.route("/turns/<int:group_id>/start", methods=["POST"])
@login_required
def turns_start(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnActionForm()
    day = turn_day_key()
    if not form.validate_on_submit():
        flash('Could not start.', 'danger')
        return redirect(url_for('turns', group_id=group.id))

    result = start_turn_session(group, day, actor_id=current_user.id)
    flash(result.message, 'success' if result.ok else 'warning')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/add_member", methods=["POST"])
@login_required
def turns_add_member(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnAddMemberForm()
    kids = User.query.filter_by(parent_id=current_user.id, role='child').order_by(User.username.asc()).all()
    existing = set(m.child_id for m in TurnGroupMember.query.filter_by(group_id=group.id).all())
    form.child_id.choices = [(k.id, k.username) for k in kids if k.id not in existing] or [(0, 'All kids already added')]

    if form.validate_on_submit() and form.child_id.data:
        if form.child_id.data == 0:
            return redirect(url_for('turns', group_id=group.id))

        max_pos = db.session.query(db.func.max(TurnGroupMember.position)).filter_by(group_id=group.id).scalar()
        next_pos = (max_pos + 1) if max_pos is not None else 0
        member = TurnGroupMember(group_id=group.id, child_id=form.child_id.data, position=next_pos)
        db.session.add(member)
        db.session.commit()

        # ensure today's state exists and is stable
        get_or_init_turn_state(group, turn_day_key())

        flash('Child added to turn group.', 'success')
    else:
        flash('Could not add child.', 'danger')

    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/settings", methods=["POST"])
@login_required
def turns_settings(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnSettingsForm()
    if form.validate_on_submit():
        new_mode = form.selection_mode.data
        group.selection_mode = new_mode
        group.auto_advance_enabled = bool(form.auto_advance_enabled.data)

        value = form.auto_advance_value.data
        unit = (form.auto_advance_unit.data or 'minutes').lower()

        if group.auto_advance_enabled:
            if value is None or value <= 0:
                flash('Auto next turn needs a time value.', 'warning')
                return redirect(url_for('turns', group_id=group.id))
            group.auto_advance_value = int(value)
            group.auto_advance_unit = unit
        else:
            group.auto_advance_value = None
            group.auto_advance_unit = unit
            group.auto_advance_paused = False

        db.session.commit()

        # New upgraded clock settings
        group.grace_period_sec = int(form.grace_period_sec.data or 120)
        group.deduct_overrun = bool(form.deduct_overrun.data)
        db.session.commit()

        # If user switches to Random during the day, apply wheel immediately once.
        if (new_mode or '').lower() == 'random':
            day = turn_day_key()
            state = get_or_init_turn_state(group, day)
            if not getattr(state, 'wheel_used', False):
                # re-init by forcing a random starter via get_or_init_turn_state logic
                # simplest: delete state row and recreate
                try:
                    db.session.delete(state)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                get_or_init_turn_state(group, day)

        flash('Turn settings saved.', 'success')
    else:
        flash('Could not save settings.', 'danger')

    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/pause", methods=["POST"])
@login_required
def turns_pause(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnPauseForm()
    if form.validate_on_submit():
        day = turn_day_key()
        result, reached = pause_turn_session(group, day, actor_id=current_user.id)
        flash(result.message, 'success' if result.ok else 'warning')

        if reached:
            # Time is up for the active turn: advance automatically
            next_result = advance_turn(group, day, actor_id=current_user.id)
            flash(next_result.message, 'success' if next_result.ok else 'warning')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/next", methods=["POST"])
@login_required
def turns_next(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnActionForm()
    if not form.validate_on_submit():
        flash('Could not advance turn.', 'danger')
        return redirect(url_for('turns', group_id=group.id))

    day = turn_day_key()
    result = advance_turn(group, day, actor_id=current_user.id)
    flash(result.message, 'success' if result.ok else 'warning')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/skip", methods=["POST"])
@login_required
def turns_skip(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnSkipForm()
    members = get_group_members(group)
    form.child_id.choices = [(m.child_id, (User.query.get(m.child_id).username if User.query.get(m.child_id) else str(m.child_id))) for m in members]
    if form.validate_on_submit():
        result = skip_turn(group, turn_day_key(), child_id=form.child_id.data, actor_id=current_user.id)
        flash(result.message, 'success' if result.ok else 'warning')
    else:
        flash('Could not skip.', 'danger')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/swap_request", methods=["POST"])
@login_required
def turns_swap_request(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnSwapRequestForm()
    kids = User.query.filter_by(parent_id=current_user.id, role='child').order_by(User.username.asc()).all()
    choices = [(k.id, k.username) for k in kids]
    form.requester_id.choices = choices
    form.target_id.choices = choices
    if form.validate_on_submit():
        result = request_swap(group, turn_day_key(), requester_id=form.requester_id.data, target_id=form.target_id.data)
        flash(result.message, 'success' if result.ok else 'warning')
    else:
        flash('Could not request swap.', 'danger')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/swap_resolve/<int:swap_id>", methods=["POST"])
@login_required
def turns_swap_resolve(group_id, swap_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    accepted = request.form.get('accepted') == '1'
    result = resolve_swap(group, turn_day_key(), swap_id=swap_id, accepted=accepted,
                          actor_id=current_user.id, parent_override=True)
    flash(result.message, 'success' if result.ok else 'warning')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/join_shared", methods=["POST"])
@login_required
def turns_join_shared(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnSharedJoinForm()
    kids = User.query.filter_by(parent_id=current_user.id, role='child').order_by(User.username.asc()).all()
    form.child_id.choices = [(k.id, k.username) for k in kids]
    if form.validate_on_submit():
        result = join_shared_turn(group, turn_day_key(), joining_child_id=form.child_id.data, actor_id=current_user.id)
        flash(result.message, 'success' if result.ok else 'warning')
    else:
        flash('Could not join shared turn.', 'danger')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/nudge", methods=["POST"])
@login_required
def turns_nudge(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    result = nudge_current_child(group, turn_day_key(), nudger_id=current_user.id)
    flash(result.message, 'success' if result.ok else 'info')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/trade", methods=["POST"])
@login_required
def turns_trade(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnTradeForm()
    kids = User.query.filter_by(parent_id=current_user.id, role='child').order_by(User.username.asc()).all()
    choices = [(k.id, k.username) for k in kids]
    form.giver_id.choices = choices
    form.receiver_id.choices = choices
    if form.validate_on_submit():
        result = execute_point_trade(group, turn_day_key(), giver_id=form.giver_id.data,
                                     receiver_id=form.receiver_id.data, points=form.points.data,
                                     actor_id=current_user.id)
        flash(result.message, 'success' if result.ok else 'warning')
    else:
        flash('Could not trade points.', 'danger')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/cal_settings", methods=["POST"])
@login_required
def turns_cal_settings(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnCalSettingsForm()
    if form.validate_on_submit():
        group.cal_mode = form.cal_mode.data
        group.cal_n_days = int(form.cal_n_days.data or 1)
        group.cal_paused = bool(form.cal_paused.data)
        db.session.commit()
        flash('Calendar settings saved.', 'success')
    else:
        flash('Could not save calendar settings.', 'danger')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/weekday_rule", methods=["POST"])
@login_required
def turns_weekday_rule(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    form = TurnWeekdayRuleForm()
    kids = User.query.filter_by(parent_id=current_user.id, role='child').order_by(User.username.asc()).all()
    form.child_id.choices = [(k.id, k.username) for k in kids]
    if form.validate_on_submit():
        rule = TurnWeekdayRule.query.filter_by(group_id=group.id, weekday=form.weekday.data).first()
        if rule:
            rule.child_id = form.child_id.data
        else:
            db.session.add(TurnWeekdayRule(group_id=group.id, weekday=form.weekday.data, child_id=form.child_id.data))
        db.session.commit()
        flash('Weekday rule saved.', 'success')
    else:
        flash('Could not save weekday rule.', 'danger')
    return redirect(url_for('turns', group_id=group.id))


@app.route("/turns/<int:group_id>/grace_check", methods=["GET"])
@login_required
def turns_grace_check(group_id):
    if current_user.role != 'parent':
        return jsonify({'error': 'forbidden'}), 403

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        return jsonify({'error': 'not found'}), 404

    fired = check_grace_warning(group, turn_day_key())
    return jsonify({'grace_fired': bool(fired)})


@app.route("/turns/<int:group_id>/history")
@login_required
def turns_history(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    day_str = request.args.get('day')
    day_val = None
    if day_str:
        try:
            day_val = date_type.fromisoformat(day_str)
        except ValueError:
            day_val = None

    logs = get_audit_log(group.id, day=day_val, limit=200)
    return render_template('turns_history.html', group=group, logs=logs, day=day_val)


@app.route("/turns/<int:group_id>/delete", methods=["POST"])
@login_required
def turns_delete_group(group_id):
    if current_user.role != 'parent':
        flash('Parents only page.', 'danger')
        return redirect(url_for('home'))

    group = TurnGroup.query.filter_by(id=group_id, parent_id=current_user.id).first()
    if not group:
        flash('Turn group not found.', 'danger')
        return redirect(url_for('turns'))

    try:
        # Delete dependent rows explicitly (TurnGroup only cascades members).
        TurnWeekdayRule.query.filter_by(group_id=group.id).delete(synchronize_session=False)
        TurnSwapRequest.query.filter_by(group_id=group.id).delete(synchronize_session=False)
        TurnAuditLog.query.filter_by(group_id=group.id).delete(synchronize_session=False)
        TurnDailyUsage.query.filter_by(group_id=group.id).delete(synchronize_session=False)
        TurnDayState.query.filter_by(group_id=group.id).delete(synchronize_session=False)
        TurnGroupMember.query.filter_by(group_id=group.id).delete(synchronize_session=False)

        db.session.delete(group)
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Could not delete group. Try again.', 'danger')
        return redirect(url_for('turns', group_id=group.id))

    flash('Turn group deleted.', 'success')
    return redirect(url_for('turns'))


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
            recurrence_interval_days=form.recurrence_interval_days.data,
            recurrence_days=r_days,
            recurrence_monthly_ordinal=form.recurrence_monthly_ordinal.data,
            recurrence_monthly_weekday=form.recurrence_monthly_weekday.data,
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
            recurrence_interval_days=form.recurrence_interval_days.data,
            recurrence_days=r_days,
            recurrence_monthly_ordinal=form.recurrence_monthly_ordinal.data,
            recurrence_monthly_weekday=form.recurrence_monthly_weekday.data,
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
    form.recurrence_interval_days.data = task.recurrence_interval_days
    form.recurrence_days.data   = [str(d) for d in task.recurrence_days_list()]
    if task.recurrence_monthly_ordinal is not None:
        form.recurrence_monthly_ordinal.data = str(task.recurrence_monthly_ordinal)
    if task.recurrence_monthly_weekday is not None:
        form.recurrence_monthly_weekday.data = str(task.recurrence_monthly_weekday)
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
        flash(f'Negative action "{form.name.data}" added.', 'warning')
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
        flash('Only parents can create consequences.', 'danger')
        return redirect(url_for('badactions'))

    form = PunishmentForm()
    if form.validate_on_submit():
        create_punishment(parent_id=current_user.id,
                          name=form.name.data,
                          crosses_threshold=form.crosses_threshold.data,
                          description=form.description.data,
                          crosses_cost=form.crosses_cost.data)
        flash(f'Consequence "{form.name.data}" added.', 'warning')
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
        flash('Only parents can delete consequences.', 'danger')
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