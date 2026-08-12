# Week 7 — Day 7 (Capstone): Deployment, Presentation & Client Handover

---

## Task 1 — Production Deployment 
The core components have been successfully containerized and deployed for the production environment. This includes:
- **FastAPI backend**
- **Voice services** (Deepgram STT & Fish Audio TTS which is now switched to Vapi which uses Deepgram Nova 3 for STT and ElevenLabs TTS)
- **LangGraph** (Stateful conversation routing and memory)
- **Vector DB** (ChromaDB for property and FAQ retrieval)
- **Database** (SQLite for structured property listings and CRM)
- **Monitoring** (built custom FastAPI endpoints)
- **CRM** (Custom CRM for agents to manage leads and appointments)

The deployment configuration can be found in the root directory:
- [Dockerfile](../Dockerfile)
- [docker-compose.yml](../docker-compose.yml)
- [main.py](../main.py) (Single deployment entrypoint)


---

### NOTE on Phone Service (VAPI): 
- For the phone service, we switched to VAPI that runs deepgram as STT, our project as custom LLM (langgraph as the orchestrator for workflow automation) and ElevenLabs as TTS.
- VAPI Credits are limited so please call carefully.
### How to Run

**1. Run using Docker (Recommended for Production)**
Navigate to the parent directory (`Week7/Day6`) and build the containers:
```powershell
cd ..
docker compose up --build
```

**2. Run locally (For Development)**
Start the FastAPI server:
```powershell
cd ..
python main.py
```

**3. Run Live Voice Agent locally**
Note: If using Windows, go to port: 8001, otherwise 8000
Start the live voice interaction:
```powershell
cd ..
python main.py --voice
```

**4. Accessing Services**
- **API Docs:** [http://localhost:8001/docs#/](http://localhost:8001/docs#/)
- **Readiness Check:** [http://localhost:8001/health/ready](http://localhost:8001/health/ready)
- **Monitoring Summary:** [http://localhost:8001/metrics/summary](http://localhost:8001/metrics/summary)

---

## Task 2 — Executive Documentation 
Comprehensive documentation has been prepared for stakeholders and operations teams. You can find these documents in the `Day7 Task2` folder:

- 🏗️ [System Architecture](Day7%20Task2/System_Architecture.md)
- 🔌 [API Documentation](Day7%20Task2/API_Documentation.md)
- 👥 [User Guide](Day7%20Task2/User_Guide.md)
- ⚙️ [Admin Guide](Day7%20Task2/Admin_Guide.md)
- 🔧 [Maintenance Guide](Day7%20Task2/Maintenance_Guide.md)
- 🚑 [Troubleshooting Guide](Day7%20Task2/Troubleshooting_Guide.md)

---

## Task 3 — Monitoring & Maintenance Plan
A defined set of targets and schedules to ensure smooth long-term operation of the voice agent. This covers latency thresholds, uptime targets, model retraining, and security cadences.

- 📊 [Monitoring & Maintenance Plan](Day7%20Task3/Monitoring_Maintenance_Plan.md)

---

## Task 4 — Stakeholder Demonstration
A structured 10-minute live demonstration script to showcase the agent's capabilities to the client. The demo covers the complete customer journey including incoming calls, RAG-powered answers, property recommendations, and Google Calendar event creation.

- 🎤 [Stakeholder Demo Script](Day7%20Task4/Stakeholder_Demo_Script.md)

---

## Task 5 — Future Enhancements
A proposal for future iterations of the product, including CRM integrations, multilingual support, and analytics dashboards to further elevate the business value of the RealEstate Hub AI Voice Agent.

- 🚀 [Future Enhancements Proposal](Day7%20Task5/Future_Enhancements.md)
