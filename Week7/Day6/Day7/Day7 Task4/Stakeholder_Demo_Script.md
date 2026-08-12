# Stakeholder Demonstration (Live Demo Script)

**Duration**: 10 Minutes
**Goal**: Showcase the complete RealEstate Hub AI Voice Agent from incoming call to post-call actions.

## Preparation
- Ensure Docker containers are running (`docker compose up`).
- Open Google Calendar and Gmail on a separate screen to show real-time updates.
- Keep the CRM database viewer open to show state changes.

## Phase 1: Incoming Call & Property Inquiry (2 minutes)
- **Action**: Initiate a call to the AI agent.
- **User (You)**: "Hello, I'm looking for a property in Lahore."
- **Agent**: (Greets and asks for preferences).
- **User**: "Mera budget 3 crore hai aur mujhe DHA Phase 6 mein apartment chahiye."
- **Demo Point**: Highlight the agent's ability to understand Urdu/English mixing and extract parameters.

## Phase 2: RAG-Powered Factual Answers & Recommendations (2 minutes)
- **Agent**: (Provides 2-3 matching apartments).
- **User**: "Are these apartments near any major hospitals or schools?"
- **Agent**: (Queries the Vector DB and answers using RAG).
- **Demo Point**: Point out that the agent is not hallucinating; it's using the local Chroma DB.
- **User**: "Us se sasti koi option hai?" (Is there a cheaper option?)
- **Agent**: (Uses recommendation memory to compare and suggest a cheaper option).

## Phase 3: Objection Handling (1.5 minutes)
- **User**: "I heard property prices in DHA Phase 6 are crashing, I'm not sure if this is a good investment."
- **Agent**: (Handles the objection professionally, providing data or reassurance without being pushy).
- **Demo Point**: Highlight the agent's sales persona and safety guardrails.

## Phase 4: Appointment Booking & Google API Integrations (2.5 minutes)
- **User**: "Okay, property number 2 ki appointment kal shaam 5 baje book kar dein."
- **Agent**: (Checks Google Calendar. *Assume the slot is free*). "Your appointment is confirmed for tomorrow at 5 PM."
- **Action**: Immediately open Google Calendar on screen to show the newly created event. 
- **Action**: Open Gmail to show the automated "Employee Notification" email detailing the client's interests.

## Phase 5: Rescheduling & Cancellation (2 minutes)
- **User**: "Actually, kal main busy hoon. Parso din 12 bajay reschedule kar dein."
- **Agent**: (Modifies the calendar event to the day after tomorrow at 12 PM).
- **Action**: Show the calendar event moving dynamically on screen.
- **User**: "You know what, just cancel it for now. I'll call back later."
- **Agent**: (Cancels the appointment and says goodbye).
- **Action**: Show the calendar event disappearing and the CRM state updating.

## Conclusion
- Briefly summarize the business value: 24/7 availability, zero missed leads, zero double-booking, and instant CRM updates.
- Open the floor for stakeholder Q&A.
