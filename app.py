
# ============================================================
# HR WORKFORCE ANALYTICS DASHBOARD
# Purpose: Visualize workforce KPIs using PostgreSQL,
# Streamlit, Pandas, and Plotly.
# ============================================================

import streamlit as st
import pandas as pd
import plotly.express as px

from sqlalchemy import create_engine, URL, text


# ============================================================
# 1. STREAMLIT PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="HR Workforce Analytics",
    page_icon="📊",
    layout="wide"
)

st.title("📊 HR Workforce Analytics Dashboard")
st.write("Interactive workforce insights from PostgreSQL")


# ============================================================
# 2. POSTGRESQL DATABASE CONNECTION
# ============================================================

@st.cache_resource
def get_database_engine():

    db = st.secrets["database"]

    database_url = URL.create(
        drivername="postgresql+psycopg",
        username=db["user"],
        password=db["password"],
        host=db["host"],
        port=db["port"],
        database=db["dbname"]
    )

    return create_engine(database_url)


# ============================================================
# 3. LOAD EMPLOYEE AND ATTENDANCE DATA
# ============================================================

@st.cache_data(ttl=60)
def load_data():

    employee_query = text("""
        SELECT
            e.employee_id,
            e.employee_name,
            e.department_id,
            d.department_name,
            e.tenure_days,
            e.termination_date
        FROM dim_employee e
        JOIN dim_department d
            ON e.department_id = d.department_id
    """)

    attendance_query = text("""
        SELECT
            f.employee_id,
            e.department_id,
            d.department_name,
            f.attendance_date,
            f.hours_worked,
            f.is_absent
        FROM fact_attendance f
        JOIN dim_employee e
            ON f.employee_id = e.employee_id
        JOIN dim_department d
            ON e.department_id = d.department_id
    """)

    with get_database_engine().connect() as conn:
        employees = pd.read_sql(employee_query, conn)
        attendance = pd.read_sql(attendance_query, conn)

    attendance["attendance_date"] = pd.to_datetime(
        attendance["attendance_date"]
    )

    attendance["hours_worked"] = pd.to_numeric(
        attendance["hours_worked"]
    )

    return employees, attendance


# ============================================================
# 4. LOAD DATA AND CREATE DEPARTMENT FILTER
# ============================================================

try:
    employees, attendance = load_data()

except Exception as error:
    st.error("Unable to load PostgreSQL data.")
    st.exception(error)
    st.stop()

st.sidebar.header("Dashboard Filters")

departments = (
    employees[["department_id", "department_name"]]
    .drop_duplicates()
    .sort_values("department_name")
)

department_options = {
    "All Departments": None
}

for row in departments.itertuples(index=False):
    department_options[
        f"{row.department_name} (ID: {row.department_id})"
    ] = row.department_id

selected_department = st.sidebar.selectbox(
    "Select Department",
    list(department_options.keys())
)

selected_id = department_options[selected_department]

if selected_id is not None:
    employees = employees[
        employees["department_id"] == selected_id
    ].copy()

    attendance = attendance[
        attendance["department_id"] == selected_id
    ].copy()


# ============================================================
# 5. KPI SUMMARY CARDS
# ============================================================

total_employees = len(employees)

total_departments = employees["department_id"].nunique()

recorded_days = len(attendance)

absent_days = int(attendance["is_absent"].sum())

absenteeism_rate = (
    absent_days / recorded_days * 100
    if recorded_days > 0 else 0
)

total_hours = attendance["hours_worked"].sum()

st.subheader("Workforce KPI Overview")

col1, col2, col3, col4 = st.columns(4)

col1.metric("Total Employees", f"{total_employees:,}")

col2.metric("Departments", f"{total_departments:,}")

col3.metric("Recorded Days", f"{recorded_days:,}")

col4.metric(
    "Absenteeism Rate",
    f"{absenteeism_rate:.2f}%"
)

st.metric(
    "Total Recorded Working Hours",
    f"{total_hours:,.1f}"
)

st.divider()


# ============================================================
# 6. GRAPH 1: DEPARTMENT-WISE ABSENTEEISM RATE
# ============================================================

st.subheader("1. Department-wise Absenteeism Rate")

dept_summary = attendance.groupby(
    ["department_id", "department_name"],
    as_index=False
).agg(
    recorded_days=("is_absent", "size"),
    absent_days=("is_absent", "sum")
)

dept_summary["absenteeism_pct"] = (
    dept_summary["absent_days"]
    / dept_summary["recorded_days"] * 100
)

fig1 = px.bar(
    dept_summary.sort_values(
        "absenteeism_pct", ascending=False
    ),
    x="department_name",
    y="absenteeism_pct",
    color="department_name",
    title="Absenteeism Rate by Department",
    labels={
        "department_name": "Department",
        "absenteeism_pct": "Absenteeism (%)"
    }
)

fig1.update_layout(showlegend=False)

st.plotly_chart(fig1, use_container_width=True)


# ============================================================
# 7. GRAPH 2: MONTHLY ABSENTEEISM TRENDS
# ============================================================

st.subheader("2. Monthly Absenteeism Trends")

monthly = attendance.copy()

monthly["month"] = (
    monthly["attendance_date"]
    .dt.to_period("M")
    .astype(str)
)

monthly_summary = monthly.groupby(
    "month", as_index=False
).agg(
    recorded_days=("is_absent", "size"),
    absent_days=("is_absent", "sum")
)

monthly_summary["absenteeism_pct"] = (
    monthly_summary["absent_days"]
    / monthly_summary["recorded_days"] * 100
)

fig2 = px.line(
    monthly_summary,
    x="month",
    y="absenteeism_pct",
    markers=True,
    title="Monthly Absenteeism Rate",
    labels={
        "month": "Month",
        "absenteeism_pct": "Absenteeism (%)"
    }
)

st.plotly_chart(fig2, use_container_width=True)


# ============================================================
# 8. GRAPH 3: EMPLOYEE TENURE DISTRIBUTION
# ============================================================

st.subheader("3. Employee Tenure Distribution")

tenure_data = employees.copy()

tenure_data["tenure_years"] = (
    tenure_data["tenure_days"] / 365.25
)

fig3 = px.histogram(
    tenure_data,
    x="tenure_years",
    nbins=15,
    title="Employee Tenure Distribution",
    labels={
        "tenure_years": "Tenure (Years)",
        "count": "Number of Employees"
    }
)

fig3.update_layout(
    xaxis_title="Tenure (Years)",
    yaxis_title="Number of Employees"
)

st.plotly_chart(fig3, use_container_width=True)


# ============================================================
# 9. GRAPH 4: DEPARTMENT-WISE ATTENDANCE HOURS
# ============================================================

st.subheader("4. Department Attendance Hours")

hours_summary = attendance.groupby(
    ["department_id", "department_name"],
    as_index=False
).agg(
    total_hours=("hours_worked", "sum")
)

fig4 = px.bar(
    hours_summary.sort_values(
        "total_hours", ascending=False
    ),
    x="department_name",
    y="total_hours",
    color="department_name",
    title="Total Recorded Working Hours by Department",
    labels={
        "department_name": "Department",
        "total_hours": "Total Working Hours"
    }
)

fig4.update_layout(showlegend=False)

st.plotly_chart(fig4, use_container_width=True)


# ============================================================
# 10. DISPLAY ATTENDANCE DATA
# ============================================================

st.subheader("Attendance Data Preview")

st.dataframe(attendance.head(100), width="stretch")


st.caption(
    "Source: PostgreSQL workforce_db | "
    "Absenteeism uses valid recorded attendance days."
)


# ============================================================
# 11. GRAPH 5: ATTENDANCE COMPLIANCE BY DEPARTMENT
# Purpose: Compare recorded days meeting the 8-hour target.
# ============================================================

st.subheader("5. Attendance Compliance by Department")

if not attendance.empty:
    compliance = attendance.copy()

    compliance["compliant"] = (
        compliance["hours_worked"] >= 8
    )

    compliance_summary = compliance.groupby(
        ["department_id", "department_name"],
        as_index=False
    ).agg(
        recorded_days=("compliant", "size"),
        compliant_days=("compliant", "sum")
    )

    compliance_summary["compliance_pct"] = (
        100 * compliance_summary["compliant_days"]
        / compliance_summary["recorded_days"]
    )

    fig5 = px.bar(
        compliance_summary,
        x="department_name",
        y="compliance_pct",
        title="Attendance Compliance Rate by Department",
        labels={
            "department_name": "Department",
            "compliance_pct": "Compliance Rate (%)"
        }
    )

    st.plotly_chart(fig5, width="stretch")

else:
    st.info("No attendance records for this selection.")


# ============================================================
# 12. GRAPH 6: POTENTIAL ATTRITION FLAGS BY DEPARTMENT
# Purpose: Count active employees meeting the ETL risk rule.
# ============================================================

st.subheader("6. Potential Attrition Flags by Department")

@st.cache_data(ttl=60)
def load_attrition_data():
    query = text("""
        SELECT
            e.employee_id,
            e.department_id,
            d.department_name,
            m.potential_attrition_risk
        FROM dim_employee e
        JOIN dim_department d
            ON e.department_id = d.department_id
        JOIN agg_employee_metrics m
            ON e.employee_id = m.employee_id
        WHERE e.termination_date IS NULL
    """)

    with get_database_engine().connect() as conn:
        return pd.read_sql(query, conn)


attrition = load_attrition_data()

if selected_id is not None:
    attrition = attrition[
        attrition["department_id"] == selected_id
    ]

attrition["is_flagged"] = (
    attrition["potential_attrition_risk"]
    .fillna(False)
    .astype(bool)
)

attrition_summary = attrition.groupby(
    ["department_id", "department_name"],
    as_index=False
).agg(
    total_active_employees=("employee_id", "count"),
    flagged_employees=("is_flagged", "sum")
)

if not attrition_summary.empty:
    fig6 = px.bar(
        attrition_summary,
        x="department_name",
        y="flagged_employees",
        title="Potential Attrition Flags by Department",
        labels={
            "department_name": "Department",
            "flagged_employees": "Flagged Employees"
        }
    )

    st.plotly_chart(fig6, width="stretch")

else:
    st.info("No active employees for this selection.")

st.caption(
    "Potential attrition flags are illustrative indicators "
    "based on absenteeism and tenure, not predictions."
)
