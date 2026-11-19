
# ============================================================
# PHASE 9: PYTHON UNIT TESTING
# Purpose: Verify employee tenure and absenteeism calculations.
# ============================================================

import pandas as pd

from Employee_etl import (
    calculate_tenure,
    compute_absenteeism_rate
)


# TEST 1: Calculate tenure for an active employee
def test_active_employee_tenure():

    hire_date = pd.to_datetime(
        pd.Series(["2024-01-01"])
    )

    termination_date = pd.to_datetime(
        pd.Series([None])
    )

    as_of = pd.Timestamp("2025-01-01")

    result = calculate_tenure(
        hire_date,
        termination_date,
        as_of
    )

    assert result.iloc[0] == 366


# TEST 2: Calculate tenure for a terminated employee
def test_terminated_employee_tenure():

    hire_date = pd.to_datetime(
        pd.Series(["2023-01-01"])
    )

    termination_date = pd.to_datetime(
        pd.Series(["2024-01-01"])
    )

    as_of = pd.Timestamp("2025-01-01")

    result = calculate_tenure(
        hire_date,
        termination_date,
        as_of
    )

    assert result.iloc[0] == 365


# TEST 3: Calculate absenteeism rate
def test_absenteeism_rate():

    absent_days = pd.Series([4])
    working_days = pd.Series([20])

    result = compute_absenteeism_rate(
        absent_days,
        working_days
    )

    assert result.iloc[0] == 0.20


# TEST 4: No absences
def test_zero_absences():

    absent_days = pd.Series([0])
    working_days = pd.Series([20])

    result = compute_absenteeism_rate(
        absent_days,
        working_days
    )

    assert result.iloc[0] == 0.0


# TEST 5: No recorded attendance days
def test_no_attendance():

    absent_days = pd.Series([0])
    working_days = pd.Series([0])

    result = compute_absenteeism_rate(
        absent_days,
        working_days
    )

    assert pd.isna(result.iloc[0])
