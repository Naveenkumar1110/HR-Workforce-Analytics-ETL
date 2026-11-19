import logging
from datetime import date
from getpass import getpass
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import URL, create_engine, text
from sqlalchemy.dialects.postgresql import insert


# Defined the required columns from the Team 4 sample CSV files.
SCHEMAS = {
    "departments": ["department_id", "department_name"],
    "employees": [
        "employee_id",
        "employee_name",
        "department_id",
        "hire_date",
        "termination_date",
        "gender",
    ],
    "attendance": [
        "attendance_id",
        "employee_id",
        "attendance_date",
        "hours_worked",
    ],
}


def validate_schema(data, required_columns, file_name):
    """Check that a source file includes every required column."""
    missing = sorted(set(required_columns) - set(data.columns))
    if missing:
        raise ValueError(f"{file_name} is missing columns: {', '.join(missing)}")


def clean_text(series):
    """Strip whitespace and treat blank strings as missing values."""
    return series.astype("string").str.strip().replace("", pd.NA)


def normalize_department_names(series):
    """Standardize spacing and case in department names."""
    return (
        clean_text(series)
        .str.replace(r"\s+", " ", regex=True)
        .str.title()
    )


def parse_id(series):
    """Convert positive whole-number IDs and mark invalid IDs as missing."""
    values = pd.to_numeric(series, errors="coerce").astype("float64")
    valid = np.isfinite(values) & values.gt(0) & values.lt(2**63)
    values = values.where(valid)
    return values.where(values.eq(values.round())).astype("Int64")


def parse_date(series):
    """Parse dates and identify missing or invalid dates with NumPy."""
    parsed = pd.to_datetime(clean_text(series), errors="coerce", format="mixed")
    dates = parsed.dt.normalize()
    missing_or_invalid = np.isnat(dates.to_numpy(dtype="datetime64[ns]"))
    return dates, missing_or_invalid


def deduplicate(data, key):
    """Keep the first accepted record for each key."""
    duplicates = data.duplicated(subset=key, keep="first")
    return data.loc[~duplicates].copy(), data.loc[duplicates].copy()


def calculate_tenure(hire_date, termination_date, as_of):
    """Calculate tenure in days using the termination date or report date."""
    return (termination_date.fillna(as_of) - hire_date).dt.days


def compute_absenteeism_rate(absent_days, working_days):
    """Calculate absenteeism and leave the rate missing if there are no days."""
    return absent_days.div(working_days.where(working_days.gt(0)))


# Created the PostgreSQL dimensions, fact table, aggregate table, and audit log.
DDL = [
    """
    create table if not exists dim_department (
        department_id bigint primary key,
        department_name text not null
    )
    """,
    """
    create table if not exists dim_employee (
        employee_id bigint primary key,
        employee_name text not null,
        department_id bigint not null references dim_department(department_id),
        hire_date date not null,
        termination_date date,
        gender text,
        tenure_days integer not null check (tenure_days >= 0),
        check (termination_date is null or termination_date >= hire_date)
    )
    """,
    """
    create table if not exists fact_attendance (
        employee_id bigint not null references dim_employee(employee_id),
        attendance_date date not null,
        hours_worked numeric not null check (hours_worked >= 0),
        is_absent boolean not null,
        primary key (employee_id, attendance_date)
    ) partition by range (attendance_date)
    """,
    """
    create table if not exists agg_employee_metrics (
        employee_id bigint primary key references dim_employee(employee_id),
        total_working_days integer not null,
        total_absent_days integer not null,
        total_hours_worked numeric not null,
        absenteeism_rate numeric,
        high_absenteeism boolean,
        potential_attrition_risk boolean
    )
    """,
    """
    create table if not exists etl_audit_log (
        audit_id bigint generated always as identity primary key,
        run_at timestamptz not null default current_timestamp,
        dataset text not null,
        rows_extracted integer not null,
        rows_rejected integer not null,
        rows_transformed integer not null,
        rows_loaded integer not null
    )
    """,
    """
    create index if not exists idx_employee_department
        on dim_employee (department_id)
    """,
    """
    create index if not exists idx_attendance_date
        on fact_attendance (attendance_date)
    """,
]


def upsert_rows(data, table_name, connection, keys):
    """Insert new rows and update matching rows using the table keys."""
    if data.empty:
        return

    def write_batch(table, conn, columns, rows):
        records = [dict(zip(columns, row)) for row in rows]
        statement = insert(table.table).values(records)
        updates = {
            column: statement.excluded[column]
            for column in columns
            if column not in keys
        }
        return conn.execute(
            statement.on_conflict_do_update(index_elements=keys, set_=updates)
        ).rowcount

    data.to_sql(
        table_name,
        connection,
        if_exists="append",
        index=False,
        chunksize=1000,
        method=write_batch,
    )


class EmployeeETL:
    def __init__(self, employees_file, departments_file, attendance_file):
        self.files = {
            "employees": Path(employees_file),
            "departments": Path(departments_file),
            "attendance": Path(attendance_file),
        }
        self.as_of = pd.Timestamp(date.today())
        self.absenteeism_threshold = 0.20
        self.short_tenure_months = 12
        self.raw = {}
        self.extracted_counts = {}
        self.rejected = []
        self.tables = {}
        self.reports = {}

    def extract(self):
        logging.info("Extracting CSV files")

        for dataset, path in self.files.items():
            corrupt_rows = []

            def capture_corrupt_row(fields):
                corrupt_rows.append(fields)
                return None

            data = pd.read_csv(
                path,
                dtype="string",
                engine="python",
                index_col=False,
                on_bad_lines=capture_corrupt_row,
            )
            validate_schema(data, SCHEMAS[dataset], path.name)
            self.raw[dataset] = data[SCHEMAS[dataset]].copy()
            self.extracted_counts[dataset] = len(data) + len(corrupt_rows)

            if corrupt_rows:
                corrupt = pd.DataFrame({"raw_record": [repr(r) for r in corrupt_rows]})
                self.record_rejections(dataset, corrupt, "Malformed CSV row")

    def record_rejections(self, dataset, rows, reason):
        if rows.empty:
            return

        rejected = rows.copy()
        rejected.insert(0, "dataset", dataset)
        rejected.insert(1, "rejection_reason", reason)
        self.rejected.append(rejected)
        logging.warning("%s | %s | %d row(s)", dataset, reason, len(rows))

    def reject(self, dataset, data, invalid, reason):
        self.record_rejections(dataset, data.loc[invalid], reason)
        return data.loc[~invalid].copy()

    def remove_duplicates(self, dataset, data, key, reason):
        clean, duplicates = deduplicate(data, key)
        self.record_rejections(dataset, duplicates, reason)
        return clean

    def validate(self):
        logging.info("Validating department, employee, and attendance records")

        # Cleaned department IDs and standardized department names.
        departments = self.raw["departments"].copy()
        departments["department_id"] = parse_id(departments["department_id"])
        departments["department_name"] = normalize_department_names(
            departments["department_name"]
        )
        departments = self.reject(
            "departments",
            departments,
            departments["department_id"].isna() | departments["department_name"].isna(),
            "Invalid department ID or missing department name",
        )
        self.departments = self.remove_duplicates(
            "departments", departments, ["department_id"], "Duplicate department ID"
        )

        # Cleaned employee IDs, names, and dates.
        employees = self.raw["employees"].copy()
        employees["employee_id"] = parse_id(employees["employee_id"])
        employees["department_id"] = parse_id(employees["department_id"])
        employees["employee_name"] = clean_text(employees["employee_name"])
        employees["gender"] = clean_text(employees["gender"]).str.upper()

        termination_entered = clean_text(employees["termination_date"]).notna()
        employees["hire_date"], invalid_hire = parse_date(employees["hire_date"])
        employees["termination_date"], invalid_end = parse_date(
            employees["termination_date"]
        )

        invalid_dates = (
            invalid_hire
            | (termination_entered & invalid_end)
            | employees["hire_date"].gt(self.as_of)
            | employees["termination_date"].gt(self.as_of)
            | employees["termination_date"].lt(employees["hire_date"])
        )
        employees = self.reject("employees", employees, invalid_dates, "Invalid hire or termination date")
        employees = self.reject(
            "employees",
            employees,
            employees["employee_id"].isna() | employees["employee_name"].isna(),
            "Invalid employee ID or missing employee name",
        )
        employees = self.reject(
            "employees",
            employees,
            ~employees["department_id"].isin(self.departments["department_id"]),
            "Employee references an unknown department",
        )
        self.employees = self.remove_duplicates(
            "employees", employees, ["employee_id"], "Duplicate employee ID"
        )

        # Cleaned attendance IDs, dates, and hours before checking employment dates.
        attendance = self.raw["attendance"].copy()
        attendance["attendance_id"] = parse_id(attendance["attendance_id"])
        attendance["employee_id"] = parse_id(attendance["employee_id"])
        attendance["attendance_date"], invalid_date = parse_date(
            attendance["attendance_date"]
        )
        attendance["hours_worked"] = pd.to_numeric(
            attendance["hours_worked"], errors="coerce"
        ).astype("float64")

        attendance = self.reject("attendance", attendance, invalid_date, "Invalid attendance date")
        attendance = self.reject(
            "attendance",
            attendance,
            attendance["attendance_id"].isna() | attendance["employee_id"].isna(),
            "Invalid attendance ID or employee ID",
        )
        attendance = self.reject(
            "attendance",
            attendance,
            ~np.isfinite(attendance["hours_worked"]) | attendance["hours_worked"].lt(0),
            "Missing, nonnumeric, or negative hours",
        )

        attendance = attendance.merge(
            self.employees[["employee_id", "hire_date", "termination_date"]],
            on="employee_id",
            how="left",
            validate="many_to_one",
        )
        attendance = self.reject(
            "attendance", attendance, attendance["hire_date"].isna(), "Unknown employee ID"
        )
        attendance = self.reject(
            "attendance",
            attendance,
            attendance["attendance_date"].lt(attendance["hire_date"])
            | attendance["attendance_date"].gt(
                attendance["termination_date"].fillna(self.as_of)
            ),
            "Attendance date outside employment period",
        )
        self.attendance = self.remove_duplicates(
            "attendance", attendance, ["attendance_id"], "Duplicate attendance ID"
        )

    def transform(self):
        logging.info("Calculating tenure and building daily attendance facts")

        self.employees["tenure_days"] = calculate_tenure(
            self.employees["hire_date"], self.employees["termination_date"], self.as_of
        )

        # Used the maximum recorded hours when one employee had multiple logs in a day.
        # Counted a day once and sorted records to handle out-of-order source logs.
        daily = (
            self.attendance.groupby(["employee_id", "attendance_date"], as_index=False)
            .agg(hours_worked=("hours_worked", "max"))
            .sort_values(["employee_id", "attendance_date"])
        )
        daily["is_absent"] = daily["hours_worked"].eq(0)

        self.tables["dim_department"] = self.departments
        self.tables["dim_employee"] = self.employees
        self.tables["fact_attendance"] = daily

    def enrich(self):
        logging.info("Calculating employee and department metrics")

        daily = self.tables["fact_attendance"]
        employee_metrics = daily.groupby("employee_id", as_index=False).agg(
            total_working_days=("attendance_date", "size"),
            total_absent_days=("is_absent", "sum"),
            total_hours_worked=("hours_worked", "sum"),
        )
        metrics = self.employees[
            ["employee_id", "hire_date", "termination_date"]
        ].merge(employee_metrics, on="employee_id", how="left", validate="one_to_one")

        count_columns = ["total_working_days", "total_absent_days"]
        metrics[count_columns] = metrics[count_columns].fillna(0).astype("int64")
        metrics["total_hours_worked"] = metrics["total_hours_worked"].fillna(0)
        metrics["absenteeism_rate"] = compute_absenteeism_rate(
            metrics["total_absent_days"], metrics["total_working_days"]
        )

        # Flagged active employees with over 20% absenteeism and under 12 months' tenure.
        has_attendance = metrics["absenteeism_rate"].notna()
        short_tenure = metrics["hire_date"].gt(
            self.as_of - pd.DateOffset(months=self.short_tenure_months)
        )
        metrics["high_absenteeism"] = (
            metrics["absenteeism_rate"].gt(self.absenteeism_threshold)
            .astype("boolean")
            .where(has_attendance)
        )
        metrics["potential_attrition_risk"] = (
            metrics["high_absenteeism"] & short_tenure
        ).where(metrics["termination_date"].isna() & has_attendance)

        self.tables["agg_employee_metrics"] = metrics.drop(
            columns=["hire_date", "termination_date"]
        )

        # Added department information to daily attendance for reporting.
        department_daily = daily.merge(
            self.employees[["employee_id", "department_id"]],
            on="employee_id",
            validate="many_to_one",
        ).merge(self.departments, on="department_id", validate="many_to_one")

        department_daily["month"] = department_daily["attendance_date"].dt.to_period("M")
        department_daily["quarter"] = department_daily["attendance_date"].dt.to_period("Q")
        self.reports["department_attendance"] = self.summarize_attendance(department_daily)
        self.reports["monthly_department_attendance"] = self.summarize_attendance(
            department_daily, ["month"]
        )
        self.reports["quarterly_department_attendance"] = self.summarize_attendance(
            department_daily, ["quarter"]
        )

    @staticmethod
    def summarize_attendance(data, period_columns=()):
        groups = ["department_id", "department_name", *period_columns]

        summary = data.groupby(groups, as_index=False).agg(
            employees_with_records=("employee_id", "nunique"),
            total_working_days=("attendance_date", "size"),
            total_absent_days=("is_absent", "sum"),
            total_hours_worked=("hours_worked", "sum"),
            avg_attendance_hours=("hours_worked", "mean"),
        )
        summary["absenteeism_rate"] = compute_absenteeism_rate(
            summary["total_absent_days"], summary["total_working_days"]
        )
        return summary

    def audit_summary(self, loaded):
        source_tables = {
            "departments": "dim_department",
            "employees": "dim_employee",
            "attendance": "fact_attendance",
        }
        rows = []
        for dataset, table in source_tables.items():
            rows.append({
                "dataset": dataset,
                "rows_extracted": self.extracted_counts[dataset],
                "rows_rejected": sum(
                    len(rejected)
                    for rejected in self.rejected
                    if rejected["dataset"].iat[0] == dataset
                ),
                "rows_transformed": len(self.tables[table]),
                "rows_loaded": loaded.get(table, 0),
            })
        rows.append({
            "dataset": "employee_metrics",
            "rows_extracted": 0,
            "rows_rejected": 0,
            "rows_transformed": len(self.tables["agg_employee_metrics"]),
            "rows_loaded": loaded.get("agg_employee_metrics", 0),
        })
        return pd.DataFrame(rows)

    def load(self, db_connection):
        logging.info("Loading PostgreSQL tables")

        for statement in DDL:
            db_connection.execute(text(statement))

        # Created only the monthly partitions needed for the cleaned attendance data.
        fact = self.tables["fact_attendance"]
        for month in fact["attendance_date"].dt.to_period("M").unique():
            partition = f"fact_attendance_{month.year}_{month.month:02d}"
            start = month.start_time.date().isoformat()
            end = (month + 1).start_time.date().isoformat()
            db_connection.execute(text(
                f"create table if not exists {partition} "
                "partition of fact_attendance "
                f"for values from ('{start}') to ('{end}')"
            ))

        keys = {
            "dim_department": ["department_id"],
            "dim_employee": ["employee_id"],
            "fact_attendance": ["employee_id", "attendance_date"],
            "agg_employee_metrics": ["employee_id"],
        }
        loaded = {}
        for name, columns in keys.items():
            data = self.tables[name].copy()
            for column in ["hire_date", "termination_date", "attendance_date"]:
                if column in data.columns:
                    data[column] = data[column].dt.date
            upsert_rows(data, name, db_connection, columns)
            loaded[name] = len(data)

        audit = self.audit_summary(loaded)
        audit.to_sql("etl_audit_log", db_connection, if_exists="append", index=False)
        return audit

    def save_csvs(self, output_dir, audit):
        output_dir.mkdir(parents=True, exist_ok=True)

        for name, data in {**self.tables, **self.reports}.items():
            data.to_csv(output_dir / f"{name}.csv", index=False)

        rejected = (
            pd.concat(self.rejected, ignore_index=True)
            if self.rejected
            else pd.DataFrame(columns=["dataset", "rejection_reason"])
        )
        rejected.to_csv(output_dir / "rejected_records.csv", index=False)
        audit.to_csv(output_dir / "etl_audit_summary.csv", index=False)

    def run(self, output_dir, engine=None):
        self.extract()
        self.validate()
        self.transform()
        self.enrich()

        audit = self.audit_summary({})
        if engine is not None:
            with engine.begin() as connection:
                audit = self.load(connection)

        self.save_csvs(Path(output_dir), audit)
        return audit


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    project_dir = Path(__file__).resolve().parent
    pipeline = EmployeeETL(
        employees_file=project_dir / "employees.csv",
        departments_file=project_dir / "departments.csv",
        attendance_file=project_dir / "attendance.csv",
    )

    # Changed this setting to True to load the same results into PostgreSQL.
    load_to_postgres = True
    engine = None

    try:
        if load_to_postgres:
            engine = create_engine(
                URL.create(
                    drivername="postgresql+psycopg",
                    username=input("PostgreSQL username: "),
                    password=getpass("PostgreSQL password: "),
                    host="localhost",
                    port=5432,
                    database=input("Existing database name: "),
                )
            )

        output_dir = project_dir / "output"
        audit = pipeline.run(output_dir, engine)
        print("\nETL audit")
        print(audit.to_string(index=False))
        print(f"\nCSV files saved in {output_dir}")
    finally:
        if engine is not None:
            engine.dispose()


