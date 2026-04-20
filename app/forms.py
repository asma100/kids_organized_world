from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SubmitField, BooleanField,
                     DateField, TimeField, IntegerField, FloatField,
                     TextAreaField, SelectField, SelectMultipleField)
from wtforms.validators import (DataRequired, Length, Email, EqualTo,
                                ValidationError, Optional, NumberRange)
from app.models import User


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
    ('weekly',  '🔁 Specific days of the week'),
    ('monthly', '🔁 Every month (same date)'),
    ('yearly',  '🔁 Every year (same date)'),
]

WEEKDAY_CHOICES = [
    ('0', 'Monday'),
    ('1', 'Tuesday'),
    ('2', 'Wednesday'),
    ('3', 'Thursday'),
    ('4', 'Friday'),
    ('5', 'Saturday'),
    ('6', 'Sunday'),
]


class CreateTaskForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired()])
    description = TextAreaField('Description')
    date = DateField('Start Date', validators=[DataRequired()])
    time = TimeField('Time', validators=[DataRequired()])

    # Recurrence
    recurrence_type = SelectField('Repeat', choices=RECURRENCE_CHOICES, default='none')
    recurrence_hours = IntegerField(
        'Every how many hours?',
        validators=[Optional(), NumberRange(min=1, max=23)],
        default=1
    )
    recurrence_days = SelectMultipleField(
        'Which days of the week?',
        choices=WEEKDAY_CHOICES,
        validators=[Optional()]
    )
    recurrence_end = DateField('Stop repeating on (optional)', validators=[Optional()])

    submit = SubmitField('Create Task')


class UpdateTaskForm(FlaskForm):
    title = StringField('Title', validators=[Optional()])
    description = TextAreaField('Description', validators=[Optional()])
    completion_status = BooleanField('Completed')

    recurrence_type = SelectField('Repeat', choices=RECURRENCE_CHOICES, default='none')
    recurrence_hours = IntegerField(
        'Every how many hours?',
        validators=[Optional(), NumberRange(min=1, max=23)],
        default=1
    )
    recurrence_days = SelectMultipleField(
        'Which days of the week?',
        choices=WEEKDAY_CHOICES,
        validators=[Optional()]
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
    submit = SubmitField('Add Reward')


class PunishmentForm(FlaskForm):
    name = StringField('Punishment Name', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=255)])
    crosses_threshold = IntegerField('Crosses Needed', validators=[DataRequired(), NumberRange(min=1)])
    submit = SubmitField('Add Punishment')


# ── Money Forms ───────────────────────────────────────────────────────────────

class AddMoneyForm(FlaskForm):
    amount = FloatField('Amount', validators=[DataRequired(), NumberRange(min=0.01)])
    note = StringField('Note (optional)', validators=[Optional(), Length(max=255)])
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
    saving_pct = IntegerField('Saving %', validators=[DataRequired(), NumberRange(min=0, max=100)])
    spending_pct = IntegerField('Spending %', validators=[DataRequired(), NumberRange(min=0, max=100)])
    donating_pct = IntegerField('Donating %', validators=[DataRequired(), NumberRange(min=0, max=100)])
    submit = SubmitField('Update Split')