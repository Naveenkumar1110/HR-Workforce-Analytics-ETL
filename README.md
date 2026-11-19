# HR Workforce Analytics ETL Pipeline

## Business Problem

Organizations need accurate workforce data to track attendance, employee tenure, absenteeism, and departmental performance. Raw HR data may contain duplicate records, missing values, invalid dates, and inconsistent employee references, making analysis difficult.

## Project Objective

Build an end-to-end ETL pipeline using Python and PostgreSQL to clean, validate, transform, and store HR data for workforce analytics.

## Technology Stack

- **Python:** ETL pipeline development
- **Pandas and NumPy:** Data cleaning and transformations
- **SQLAlchemy and Psycopg:** PostgreSQL connectivity and data loading
- **PostgreSQL:** Relational data storage and SQL analytics
- **Pytest:** Unit testing
- **pgAdmin:** Database administration and SQL execution

## ETL Architecture

Raw CSV Files → Python Extraction → Data Validation → Transformation → KPI Enrichment → PostgreSQL → SQL Analytics → Reporting

## Source Data

- `employees.csv` — Employee details, departments, hiring and termination dates
- `departments.csv` — Department IDs and names
- `attendance.csv` — Employee attendance dates and recorded working hours

## Database Design

The PostgreSQL database contains:

- `dim_department` — Clean department information
- `dim_employee` — Employee details and tenure
- `fact_attendance` — Daily attendance records
- `agg_employee_metrics` — Employee-level workforce KPIs
- `etl_audit_log` — ETL execution statistics

## Key Workforce Metrics

Employee tenure, absenteeism rate, attendance hours, department attendance, monthly absenteeism trends, turnover estimates, attendance compliance, and rule-based potential attrition indicators.

## Data Quality

The ETL pipeline validates source schemas, identifies invalid dates and IDs, rejects duplicate and orphan records, checks attendance values, and generates rejection and audit reports.

## ETL Execution Summary

The successful sample run processed:

- 20 departments
- 1,100 source employee records
- 15,000 source attendance records

After cleaning and transformation, it loaded:

- 20 departments
- 848 employees
- 8,241 daily attendance records
- 848 employee metric records

## Business Value

The solution improves workforce data quality, enables repeatable ETL processing, and provides structured information for analyzing workforce attendance and operational trends.

## Future Enhancement

Build an interactive Streamlit dashboard with Plotly visualizations connected directly to PostgreSQL.