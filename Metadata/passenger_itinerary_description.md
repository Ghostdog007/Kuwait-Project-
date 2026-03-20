# Metadata: passenger_itinerary_v11.xlsx

## 1. Overview

This spreadsheet acts as a transport and shift coordinator, mapping employee work schedules to a company-managed bus system. Each row represents a single employee's daily commute plan linked to their shift.

---

## 2. Key Fields

* **Employee Information:** Employee ID and Employee Name.
* **Workplace:** Store identifies the brand and location (e.g., KFC, Hardees, Baskin Robbins).
* **Scheduling:** Shift Start and Shift End define the daily work window.
* **Logistics:** Transport Leg 1 and Transport Leg 2 specify the commute details, including:
  * Bus Number
  * Trip Direction (IN, OUT, or MIXED)
  * Boarding Time
  * Drop-off Time

---

## 3. Example Entry

For an employee named **Hassan Salem Mohamed Medany (ID: 11001469)**:

* **Store:** TGIF - Al Kout Mall
* **Shift:** 01:30 PM to 10:30 PM
* **Transport Leg 1 (To Work):** Bus 4 (IN) | Board: 12:19 PM | Drop: 12:29 PM
* **Transport Leg 2 (From Work):** Bus 7 (OUT) | Board: 10:30 PM | Drop: 10:40 PM

---

## 4. Purpose and Usage

The primary purpose of this data is to synchronize staff availability with transportation routes to ensure employees arrive and depart their respective stores according to their scheduled shifts. It supports:

* Aligning shift times with pickup and drop schedules
* Coordinating inbound and outbound transport legs per employee
* Validating that transport legs cover the full shift window
* Capacity and routing analysis for staff transport planning
