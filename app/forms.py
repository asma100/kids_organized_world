from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SubmitField, BooleanField,
                     DateField, TimeField, IntegerField, FloatField, TextAreaField)
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, Optional, NumberRange
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


class CreateTaskForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired()])
    description = StringField('Description', validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()])
    time = TimeField('Time', validators=[DataRequired()])
    submit = SubmitField('Create Task')


class UpdateTaskForm(FlaskForm):
    title = StringField('Title', validators=[Optional()])
    description = StringField('Description', validators=[Optional()])
    completion_status = BooleanField('Completed')
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