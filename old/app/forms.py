from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SubmitField, BooleanField,
                     DateField, TimeField, IntegerField, FloatField,
                     TextAreaField, SelectField, SelectMultipleField)
from wtforms.validators import (DataRequired, Length, Email, EqualTo,
                                ValidationError, Optional, NumberRange)
from app.models import User

from flask_wtf.file import FileField, FileAllowed

from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed
from wtforms import (StringField, SubmitField, BooleanField,
                     DateField, TimeField, IntegerField,
                     TextAreaField, SelectField, SelectMultipleField)
from wtforms.validators import DataRequired, Optional, NumberRange


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password',
                                     validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

    def validate_username(self, username):
        if User.query.filter_by(username=username.data).first():
            raise ValidationError('That username is taken.')

    def validate_email(self, email):
        if User.query.filter_by(email=email.data).first():
            raise ValidationError('That email is taken.')


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')



RECURRENCE_CHOICES = [
    ('none',    '📅 No repeat (one-time)'),
    ('daily',   '🔁 Every day'),
    ('hourly',  '🔁 Every N hours'),
    ('interval_days', '🔁 Every N days'),
    ('weekly',  '🔁 Specific days of the week'),
    ('monthly', '🔁 Every month (same date)'),
    ('monthly_weekday', '🔁 Monthly (e.g. 1st Monday)'),
    ('yearly',  '🔁 Every year (same date)'),
]
 
WEEKDAY_CHOICES = [
    ('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'),
    ('3', 'Thursday'), ('4', 'Friday'), ('5', 'Saturday'), ('6', 'Sunday'),
]

MONTHLY_ORDINAL_CHOICES = [
    ('1', '1st'),
    ('2', '2nd'),
    ('3', '3rd'),
    ('4', '4th'),
    ('-1', 'Last'),
]
 
ALLOWED_IMAGE_TYPES = ['png', 'jpg', 'jpeg', 'gif', 'webp']
 
 
class CreateTaskForm(FlaskForm):
    title       = StringField('Title', validators=[DataRequired()])
    description = TextAreaField('Description')
    date        = DateField('Start Date', validators=[DataRequired()])
    time        = TimeField('Time', validators=[DataRequired()])
 
    # Task image — shown as a small square next to the title
    image = FileField(
        'Task Image (optional — helps kids who cannot read yet)',
        validators=[
            Optional(),
            FileAllowed(ALLOWED_IMAGE_TYPES, 'Images only!')
        ]
    )
 
    recurrence_type = SelectField('Repeat', choices=RECURRENCE_CHOICES, default='none')
    recurrence_hours = IntegerField(
        'Every how many hours?',
        validators=[Optional(), NumberRange(min=1, max=23)],
        default=1
    )
    recurrence_interval_days = IntegerField(
        'Every how many days?',
        validators=[Optional(), NumberRange(min=1, max=365)],
        default=2,
    )
    recurrence_days = SelectMultipleField(
        'Which days of the week?',
        choices=WEEKDAY_CHOICES,
        validators=[Optional()]
    )
    recurrence_monthly_ordinal = SelectField(
        'Which week of the month?',
        choices=MONTHLY_ORDINAL_CHOICES,
        validators=[Optional()],
        default='1',
    )
    recurrence_monthly_weekday = SelectField(
        'Which weekday?',
        choices=WEEKDAY_CHOICES,
        validators=[Optional()],
        default='0',
    )
    recurrence_end = DateField('Stop repeating on (optional)', validators=[Optional()])
 
    submit = SubmitField('Create Task')


class ParentBulkCreateTaskForm(FlaskForm):
    all_kids = BooleanField('All kids')
    child_ids = SelectMultipleField('Kids', coerce=int, validators=[Optional()])

    title = StringField('Title', validators=[DataRequired()])
    description = TextAreaField('Description')
    date = DateField('Start Date', validators=[DataRequired()])
    time = TimeField('Time', validators=[DataRequired()])

    recurrence_type = SelectField('Repeat', choices=RECURRENCE_CHOICES, default='none')
    recurrence_hours = IntegerField(
        'Every how many hours?',
        validators=[Optional(), NumberRange(min=1, max=23)],
        default=1,
    )
    recurrence_interval_days = IntegerField(
        'Every how many days?',
        validators=[Optional(), NumberRange(min=1, max=365)],
        default=2,
    )
    recurrence_days = SelectMultipleField(
        'Which days of the week?',
        choices=WEEKDAY_CHOICES,
        validators=[Optional()],
    )
    recurrence_monthly_ordinal = SelectField(
        'Which week of the month?',
        choices=MONTHLY_ORDINAL_CHOICES,
        validators=[Optional()],
        default='1',
    )
    recurrence_monthly_weekday = SelectField(
        'Which weekday?',
        choices=WEEKDAY_CHOICES,
        validators=[Optional()],
        default='0',
    )
    recurrence_end = DateField('Stop repeating on (optional)', validators=[Optional()])

    submit = SubmitField('Create Task For Selected')

    def validate(self, extra_validators=None):
        rv = super().validate(extra_validators=extra_validators)
        if not rv:
            return False
        if not self.all_kids.data and not self.child_ids.data:
            self.child_ids.errors.append('Select at least one kid or choose All kids.')
            return False
        return True
 
 
class UpdateTaskForm(FlaskForm):
    title       = StringField('Title', validators=[Optional()])
    description = TextAreaField('Description', validators=[Optional()])
    completion_status = BooleanField('Completed')
 
    # Upload a new image or leave blank to keep existing
    image = FileField(
        'Change Image (leave blank to keep current)',
        validators=[
            Optional(),
            FileAllowed(ALLOWED_IMAGE_TYPES, 'Images only!')
        ]
    )
    # Checkbox to remove the existing image entirely
    remove_image = BooleanField('Remove current image')
 
    recurrence_type = SelectField('Repeat', choices=RECURRENCE_CHOICES, default='none')
    recurrence_hours = IntegerField(
        'Every how many hours?',
        validators=[Optional(), NumberRange(min=1, max=23)],
        default=1
    )
    recurrence_interval_days = IntegerField(
        'Every how many days?',
        validators=[Optional(), NumberRange(min=1, max=365)],
        default=2,
    )
    recurrence_days = SelectMultipleField(
        'Which days of the week?',
        choices=WEEKDAY_CHOICES,
        validators=[Optional()]
    )
    recurrence_monthly_ordinal = SelectField(
        'Which week of the month?',
        choices=MONTHLY_ORDINAL_CHOICES,
        validators=[Optional()],
        default='1',
    )
    recurrence_monthly_weekday = SelectField(
        'Which weekday?',
        choices=WEEKDAY_CHOICES,
        validators=[Optional()],
        default='0',
    )
    recurrence_end = DateField('Stop repeating on (optional)', validators=[Optional()])
 
    submit = SubmitField('Update Task')


# ── Good / Bad Action Forms ───────────────────────────────────────────────────

class GoodActionForm(FlaskForm):
    name = StringField('Action Name', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=255)])
    points_value = IntegerField('Points', validators=[DataRequired(), NumberRange(min=1, max=100)])
    submit = SubmitField('Save Action')


class BadActionForm(FlaskForm):
    name = StringField('Action Name', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=255)])
    crosses_value = IntegerField('Crosses', validators=[DataRequired(), NumberRange(min=1, max=100)])
    submit = SubmitField('Save Action')


class RewardForm(FlaskForm):
    name = StringField('Reward Name', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=255)])
    points_threshold = IntegerField('Points Needed', validators=[DataRequired(), NumberRange(min=1)])
    points_cost = IntegerField('Points Cost (optional)', validators=[Optional(), NumberRange(min=0)])
    submit = SubmitField('Add Reward')


class PunishmentForm(FlaskForm):
    name = StringField('Punishment Name', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=255)])
    crosses_threshold = IntegerField('Crosses Needed', validators=[DataRequired(), NumberRange(min=1)])
    crosses_cost = IntegerField('Crosses Cost (optional)', validators=[Optional(), NumberRange(min=0)])
    submit = SubmitField('Add Punishment')


# ── Money Forms ───────────────────────────────────────────────────────────────

class AddMoneyForm(FlaskForm):
    amount = FloatField('Amount', validators=[DataRequired(), NumberRange(min=0.01)])
    note = StringField('Note (optional)', validators=[Optional(), Length(max=255)])
    add_mode = SelectField(
        'When adding',
        choices=[
            ('unassigned', 'Add without deciding (Unassigned)'),
            ('auto_split', 'Auto split into jars now'),
        ],
        validators=[DataRequired()],
    )
    saving_pct = IntegerField('Saving %', validators=[Optional(), NumberRange(min=0, max=100)])
    spending_pct = IntegerField('Spending %', validators=[Optional(), NumberRange(min=0, max=100)])
    donating_pct = IntegerField('Kindness %', validators=[Optional(), NumberRange(min=0, max=100)])
    submit = SubmitField('Add Money')


class SpendMoneyForm(FlaskForm):
    amount = FloatField('Amount', validators=[DataRequired(), NumberRange(min=0.01)])
    note = StringField('Note (optional)', validators=[Optional(), Length(max=255)])
    submit = SubmitField('Confirm')


class SavingsGoalForm(FlaskForm):
    name = StringField('Goal Name', validators=[DataRequired(), Length(max=100)])
    target_amount = FloatField('Target Amount', validators=[DataRequired(), NumberRange(min=0.01)])
    reward_description = StringField('Reward when achieved', validators=[Optional(), Length(max=255)])
    submit = SubmitField('Set Goal')


class SplitForm(FlaskForm):
    saving_pct = IntegerField('Saving %', validators=[Optional(), NumberRange(min=0, max=100)])
    spending_pct = IntegerField('Spending %', validators=[Optional(), NumberRange(min=0, max=100)])
    donating_pct = IntegerField('Kindness %', validators=[Optional(), NumberRange(min=0, max=100)])
    submit = SubmitField('Update Split')


class GoalDepositForm(FlaskForm):
    amount = FloatField('Deposit Amount', validators=[DataRequired(), NumberRange(min=0.01)])
    submit = SubmitField('Add To Goal')


class CreateChildForm(FlaskForm):
    username = StringField('Child Username', validators=[DataRequired(), Length(max=20)])
    email = StringField('Email (optional)', validators=[Optional(), Email()])
    submit = SubmitField('Create Child')


# ── Turns (MVP) ───────────────────────────────────────────────────────────────

class TurnGroupForm(FlaskForm):
    name = StringField('Turn Group Name', validators=[DataRequired(), Length(max=80)])
    turn_duration_min = IntegerField('Turn Duration (minutes)', validators=[Optional(), NumberRange(min=1, max=180)], default=30)
    daily_quota_min = IntegerField('Daily Quota (minutes per child)', validators=[Optional(), NumberRange(min=1, max=24*60)], default=120)
    submit = SubmitField('Create Turn Group')


class TurnAddMemberForm(FlaskForm):
    child_id = SelectField('Add Child', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Add')


class TurnSettingsForm(FlaskForm):
    selection_mode = SelectField(
        'Next turn selection',
        choices=[
            ('round_robin', 'In order'),
            ('random', 'Random'),
        ],
        validators=[DataRequired()],
        default='round_robin',
    )

    auto_advance_enabled = BooleanField('Auto next turn')
    auto_advance_value = IntegerField('Every', validators=[Optional(), NumberRange(min=1, max=9999)])
    auto_advance_unit = SelectField(
        'Unit',
        choices=[
            ('seconds', 'Seconds'),
            ('minutes', 'Minutes'),
            ('hours', 'Hours'),
        ],
        validators=[DataRequired()],
        default='minutes',
    )

    grace_period_sec = IntegerField('Grace Period (sec)', validators=[Optional(), NumberRange(min=0, max=3600)], default=120)
    deduct_overrun = BooleanField('Deduct overrun from tomorrow', default=True)

    submit = SubmitField('Save Settings')


class TurnPauseForm(FlaskForm):
    submit = SubmitField('Pause')


class TurnActionForm(FlaskForm):
    submit = SubmitField('Go')


class TurnSkipForm(FlaskForm):
    child_id = SelectField('Skip child', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Skip to End')


class TurnSwapRequestForm(FlaskForm):
    requester_id = SelectField('Child requesting swap', coerce=int, validators=[DataRequired()])
    target_id = SelectField('Swap with', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Request Swap')


class TurnSharedJoinForm(FlaskForm):
    child_id = SelectField('Child joining', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Join Shared Turn')


class TurnNudgeForm(FlaskForm):
    submit = SubmitField('Nudge')


class TurnTradeForm(FlaskForm):
    giver_id = SelectField('Giver (paying points)', coerce=int, validators=[DataRequired()])
    receiver_id = SelectField('Receiver (giving up slot)', coerce=int, validators=[DataRequired()])
    points = IntegerField('Points', validators=[DataRequired(), NumberRange(min=1, max=10**9)])
    submit = SubmitField('Execute Trade')


class TurnCalSettingsForm(FlaskForm):
    cal_mode = SelectField(
        'Calendar Mode',
        choices=[
            ('n_day', 'Every N Days'),
            ('weekday', 'Fixed Weekdays'),
            ('cyclical', 'Monthly/Yearly (simple)'),
        ],
        validators=[DataRequired()],
        default='n_day',
    )
    cal_n_days = IntegerField('Rotate every N days', validators=[Optional(), NumberRange(min=1, max=365)], default=1)
    cal_paused = BooleanField('Pause rotation (holiday)')
    submit = SubmitField('Save Calendar Settings')


class TurnWeekdayRuleForm(FlaskForm):
    weekday = SelectField(
        'Day',
        coerce=int,
        choices=[(0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
                 (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday')],
        validators=[DataRequired()],
    )
    child_id = SelectField('Child', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Set Rule')