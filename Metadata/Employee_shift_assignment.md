# Metadata: Employee Shift Assignment

## 1. Overview

**File Name:** `Employee_Shift_Assignment.xlsx`  
**Primary Sheet:** `Sheet1`  
**Description:** This dataset contains standard shift schedules for employees across various restaurant brands (KFC, Hardees, TGIF, Tikka, Baskin Robbins, etc.). It maps employee identification numbers and names to specific store locations and their assigned working hours.

---

## 2. Data Schema (`Sheet1`)

| Column Name | Data Type | Description | Example |
| :-- | :-- | :-- | :-- |
| **EMPLOYEE_NUMBER** | String/ID | Unique identifier for the employee. | `11001275` |
| **EMPLOYEE_NAME** | String | Full name of the employee. | `Mohamed Darwesh Moustafa` |
| **STORE_NAME** | String | The specific restaurant brand and location. | `KFC - Bayan` |
| **Standard_Shift_Start_Time** | Time | The scheduled start time (12-hour format). | `11:30 AM` |
| **Standard_Shift_End_Time** | Time | The scheduled end time (12-hour format). | `08:30 PM` |

---

## 3. Agent Usage Instructions

### A. Querying and Searching

* **Finding Shifts by Employee:** To find when a specific person works, search the `EMPLOYEE_NAME` column (Column B).
* **Store Rosters:** To see all employees at a specific location, filter `STORE_NAME` (Column C). Note that store names often follow the pattern `[Brand] - [Location]`.

### B. Analysis and Calculations

* **Calculating Duration:** Since shifts often cross the midnight boundary (e.g., `03:30 PM` to `12:30 AM`), use the following logic for duration:
  `=(End_Time - Start_Time) + IF(End_Time < Start_Time, 1, 0)`
* **Brand Aggregation:** You can group data by Brand (e.g., all "KFC" or all "Hardees") using `TEXT_CONTAINS` filters or wildcard searches in Column C.

### C. Suggested Actions for the Agent

1. **Shift Overlap Analysis:** Identify employees at the same store whose start times coincide.
2. **Night Shift Identification:** Flag or filter shifts where `Standard_Shift_End_Time` is between `12:00 AM` and `06:00 AM`.
3. **Roster Formatting:**
   * Add a Checkbox column for "Attendance" or "Verification".
   * Use Conditional Formatting to highlight shifts longer than 9 hours.
   * Add a Dropdown menu to a new column for "Status" (e.g., Present, Absent, On Leave).

---

## 4. Constraints and Nuances

* **Time Formats:** The times are stored in AM/PM format. When writing formulas for comparison, ensure the agent treats them as time values, not just strings.
* **Data Volume:** The table contains over 2,700 rows. Always use specific range references (e.g., `A2:E2726`) rather than whole-column references to optimize performance.
* **Duplicates:** Some stores may have multiple entries for the same employee if they work split shifts (though not currently visible in the active context, the agent should verify).

---

## 5. Quick Tools Reference

* **Filter for Brand:** `sheets:add_filter(range="A1:E2726", filters=[{"column_range": "C2:C2726", "condition": "TEXT_CONTAINS", "condition_values": ["KFC"]}])`
* **Highlight Late Shifts:** `sheets:add_conditional_format(range="D2:D2726", condition="CUSTOM_FORMULA", condition_values=["=HOUR(D2)>=18"], hex_color="#FF9900")` (Highlights shifts starting at or after 6 PM).
