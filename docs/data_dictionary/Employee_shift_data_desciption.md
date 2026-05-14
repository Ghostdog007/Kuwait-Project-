### Dataset Description: Employee Information Dataset(Info is about Employee_shift_Assignment.xlsx)

This dataset contains **employee-level information related to store operations and accommodation assignments**. Each row represents a **single employee** along with their identification details, workplace store, accommodation information, and role.

The dataset links employees to **stores, area coaches (supervisors), and accommodation locations**, making it useful for workforce management and logistics analysis.

#### Columns

* **#**
  Sequential row identifier.

* **EMPLOYEE CODE**
  Unique identifier assigned to each employee.

* **Stay**
  Indicates whether the employee is currently staying in company-provided accommodation or housing.

* **EMPLOYEE NAME**
  Full name of the employee.

* **code**
  Internal or system code related to the employee record.

* **Accommodation Id**
  Unique identifier for the accommodation facility assigned to the employee.

* **Accommodation Name**
  Name of the accommodation or housing facility where the employee resides.

* **Area Coach Name**
  Name of the area supervisor or manager responsible for the employee.

* **Store ID**
  Unique identifier of the store where the employee works.

* **Store Name**
  Name of the store where the employee is assigned.

* **gender**
  Gender of the employee.

* **POSITION**
  Job role or position of the employee within the store (e.g., crew member, supervisor, etc.).

#### Dataset Purpose

The dataset is primarily used for **employee management and operational logistics**, including:

* Mapping employees to stores
* Tracking accommodation assignments
* Workforce planning and scheduling
* Staff distribution analysis across locations
* Supervisor-to-employee relationships

Each record corresponds to **one employee and their associated operational details**.

---

### Additional Metadata Provided (Weekly Shift Schedule Context)

This spreadsheet, **"Input - Employee Shift data.xlsx,"** serves as a weekly shift schedule for employees across multiple restaurant brands (Wimpy, BR, TGIF, KFC, Hardees, CT, and KK) for the week of **April 5th to April 11th, 2026**.

#### File Metadata and Structure

* **Overall Purpose**: Tracking workforce shift times, store assignments, and employee roles across various locations and brands.
* **Sheet Organization**: Each tab represents a specific brand or group of stores (e.g., "Wimpy," "KFC").
* **Header Structure**:
  * **Row 1**: Shift labels (Start/End).
  * **Row 2**: Specific dates.
  * **Row 3**: Core column headers.
  * **Row 4 onwards**: Employee records.

#### Key Fields (Columns A - H)

* **EMPLOYEE CODE (B)**: Unique identification number for each staff member.
* **EMPLOYEE NAME (C)**: Full name of the employee.
* **Accommodation Name (D)**: The staff housing or location associated with the employee.
* **Store ID (E) and Store Name (G)**: Specific identifiers for the restaurant location where the shift is worked.
* **Brand (F)**: The restaurant chain (e.g., Wimpy).
* **POSITION (H)**: The employee's role (e.g., Team Member, Shift Supervisor, Restaurant General Manager).

#### Shift Data (Columns I - AJ)

The shift data follows a repeating 4-column pattern for each day of the week:

1. **Shift Start**: The starting time for the primary shift.
2. **Shift End**: The ending time for the primary shift.
3. **Shift Start 2**: The starting time for a second (split) shift, if applicable.
4. **Shift End 2**: The ending time for the second (split) shift, if applicable.

**Daily Ranges**:

* **Sunday**: I:L
* **Monday**: M:P
* **Tuesday**: Q:T
* **Wednesday**: U:X
* **Thursday**: Y:AB
* **Friday**: AC:AF
* **Saturday**: AG:AJ
