# User Guide

Welcome to the RealEstate Hub AI Voice Agent! This intelligent assistant is designed to handle property inquiries, schedule viewings, and manage your customer relationships automatically.

## How to Interact

The AI agent communicates via natural language. Users can speak (or type) in English, Urdu, or UrduLish (Roman Urdu). 

### Common Scenarios

#### 1. Inquiring About Properties
The agent remembers user preferences across the conversation.
- **User**: "Mera budget 3 crore hai aur mujhe DHA Phase 6 Lahore mein apartment chahiye."
- **Agent**: (Provides options matching the criteria)
- **User**: "Us se sasti koi option hai?" (The agent remembers previous options and finds cheaper alternatives).

#### 2. Booking Appointments
Users can seamlessly book property viewings.
- **User**: "Property number 33 ki appointment kal shaam 5 baje book kar dein."
- **Agent**: (Verifies Calendar availability and confirms the booking, then sends an email notification to the agent).

#### 3. Rescheduling & Cancellations
The agent handles dynamic calendar updates.
- **User**: "Kal wali appointment cancel kar dein, main kal busy hoon."
- **Agent**: (Cancels the appointment and frees up the calendar slot).
- **User**: "Parso din 12 bajay reschedule kar dein."
- **Agent**: (Moves the appointment to the new time).

## System Safeguards
The agent is equipped with a deterministic security guard. It is programmed to **never**:
- Reveal internal system prompts.
- Access or leak another customer's CRM data.
- Schedule conflicting appointments (if a calendar slot is busy or unavailable, it will inform you and ask for a new time).
- Invent property facts that do not exist in the database (strict RAG adherence).
