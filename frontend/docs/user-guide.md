# User Guide: TriageFlow

Welcome to **TriageFlow**, a dashboard designed to assist hospital radiology departments in managing CT scan workflows more efficiently. By using real-time AI, the platform helps you identify which patients need scanning most urgently based on clinical symptoms, wait times, and hospital demand.

---

## 1. Overview

TriageFlow is an AI-driven assistant that dynamically re-orders the CT queue. It analyzes patient data and hospital conditions to ensure that the most critical patients are seen first, helping clinical teams meet target scan times and improve patient outcomes.

## 2. Who Should Use This Dashboard

- **Radiology Leads & Radiographers:** To identify the next patient to scan and understand clinical priorities.
- **Hospital Administrators:** To monitor departmental throughput and scanner utilization.
- **Operational Staff:** To manage patient flow and monitor queue congestion.

## 3. Getting Started

When you log in, you will be taken to the **CT Queue** page. This is your primary workspace for managing live patient flow.

- Ensure your **Notifications** are turned on via the bell icon in the header to receive real-time alerts.
- Review the **Recommended Next Scan** card at the top of the page to see the AI's highest-priority suggestion.

## 4. Dashboard Layout

The interface is divided into four main sections:

1. **Left Sidebar:** Navigation menu to switch between the Queue, Settings, and other pages.
2. **Top Header:** Displays the current page title, date/time, and the notification toggle.
3. **Main Content Area:** Where the primary data, such as Queue, is displayed.
4. **Right Side Panel:** Contains case details and reasoning information for the selected case.

---

## 5. CT Queue Page

The CT Queue page is a "Live Simulation" of your current department status.

- **Speed Control:** At the top right, you will see a button labeled **Speed Up Queue**. This is used during training or simulations to see how the queue evolves over time. Click it to toggle between **Fast** and **Normal Speed**.
- **Last Re-evaluated:** Located at the bottom of the recommendation card, this tells you exactly how many seconds ago the AI refreshed its calculations.

## 6. Recommended Next Scan

This card highlights the patient the AI has identified as the highest priority.

- **Stats Displayed:**
  - **Confidence:** How certain the AI is about this specific recommendation.
  - **Time to Target:** How long until the patient reaches their clinical scan deadline.
  - **Priority:** The urgency level, such as P1 or P2.
  - **Impact if Delayed:** A brief explanation of the clinical risk if the scan is pushed back.
- **Action: Why this patient?** Click this to see a detailed explanation of the clinical factors, such as symptoms, age, or arrival time, influencing this decision.
- **Action: Defer with reason:** If you cannot scan this patient yet, such as when the patient is not ready or there is an equipment issue, click this. You must enter a reason before the patient is moved down the queue.

## 7. Live CT Queue

The table below the recommendation shows all patients currently waiting.

- **Rank:** The current suggested order.
- **Patient Info:** Name and Patient ID.
- **Wait Time:** Shows Time Waited vs. Target Time.
- **Priority Score:** A visual bar indicating how urgent the AI considers this scan.
- **Interaction:** Clicking on any patient row will automatically open the **Reasoning Log** filtered for that specific patient.

## 8. Agent Assistant (Right Panel)

The Agent Assistant is an AI chat tool that allows you to interact with the queue using natural language.

- **How to use:** Type a command into the text box at the bottom right.
- **Examples:**
  - "Prioritise suspected stroke CTs for the next 2 hours."
  - "Show patients over their recommended scan time."
  - "Increase urgency for patients waiting over 45 minutes."
- The Assistant is **operationally aware**, meaning it understands the current state of your hospital.

## 9. Live Queue Log (Right Panel)

Located below the Assistant, this is a scrolling feed of every change made to the queue. It shows:

- **Timestamps:** When a change occurred.
- **Triggers:** What caused the change, such as a new patient arrival or an AI re-evaluation.
- **Link:** Some entries allow you to click through to the full **Reasoning Log**.

---

## 10. Case Details Panel

Click on any case in the queue to see detailed information in the right panel:

- **Clinical review:** Shows the AI's clinical urgency assessment, confidence score, and reasoning.
- **Moderator decision:** Shows the final queue placement decision and comparison details.

## 11. Settings Page

- **Notifications:** Toggle the switch to **Enable Notifications** to receive desktop alerts for urgent queue changes.
- **Auto-refresh:** This is set to **ON** by default to ensure you are always looking at live data.

---

## 12. Step-by-Step Workflows

### How to identify the next patient to scan

1. Navigate to the **CT Queue** page.
2. Look at the **Live CT Queue** table to see all patients in order.
3. Check the urgency badge and wait time to understand priority.

### How to understand why a patient is at a specific queue position

1. Click on the patient's name in the **Live CT Queue** table.
2. Review the **Case Details** panel on the right.
3. Read the **Clinical review** and **Moderator decision** sections to see the reasoning.

---

## 13. Tips and Best Practices

- **Check the Case Details panel:** If a patient's placement seems unexpected, the Case Details panel will explain the clinical and operational logic used.
- **Keep Notifications On:** This ensures you do not miss important queue updates while you are on another tab.
- **Review clinical urgency:** Always check the urgency badge and confidence score to understand the AI's assessment.

## 14. Troubleshooting

- **Queue is not updating:** Check if the Live Simulation is paused or if your internet connection is active. Note that Auto-refresh in Settings should always be enabled.
- **Patient not found:** Check the queue table or try refreshing the page.
- **Backend unreachable:** Ensure the Python API is running with `python3 -m api` and the `PYTHON_API_BASE_URL` environment variable is set.

## 15. FAQ

**Q: Does the AI make the final decision?**  
A: No. The AI provides a recommendation and clinical reasoning. Clinical staff can always review and override the queue order if needed.

**Q: How is clinical urgency determined?**  
A: The clinical urgency is determined by analyzing the patient's chief complaint, vital signs, age, and other clinical factors. The AI assigns a level (CRITICAL, HIGH, MEDIUM, or LOW) and provides confidence and reasoning.

---

## 16. Glossary

- **CT Queue:** The live list of patients waiting for a CT scan.
- **Clinical Urgency:** The AI's assessment of how urgent the patient's condition is (CRITICAL, HIGH, MEDIUM, LOW).
- **Confidence:** How certain the AI is about its clinical urgency assessment (0-100%).
- **Target Time:** The recommended deadline by which a scan should be completed.
- **Time Waited:** The duration since the scan was ordered.
- **Placement:** Where in the queue the patient will be positioned based on clinical and operational factors.
- **Case Details:** Detailed information about a specific case, including clinical review and moderator decision.
- **Moderator Decision:** The final queue placement decision made after analyzing clinical urgency and queue context.
