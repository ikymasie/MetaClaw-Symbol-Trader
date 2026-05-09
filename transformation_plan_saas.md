# MetaClaw SaaS Transformation Plan

## 🎯 Objective
Transition MetaClaw from a single-user local script to a premium, containerized SaaS platform where users deploy their own isolated instances (Docker) linked to a central Firebase backend.

## 🏗️ Architecture Overview
- **Deployment**: One Docker container per user (Local Windows/macOS).
- **Core**: Python Backend (FastAPI) + MT5 (via Wine/Bridge).
- **State**: Firebase (Auth, Firestore, Storage) as the source of truth.
- **Frontend**: Next.js dashboard + Multi-step Onboarding Wizard.

---

## 🛠️ Phase 1: Data Model & Persistence (Broker-Specific)
- [ ] **Models**: Update `backend/models.py` with `BrokerAccount` and `UserConfig`.
- [ ] **Bot Binding**: Bind `BotConfig` to a specific `account_id`.
- [ ] **Firebase**: Update `firebase_store.py` to support `users/{uid}/accounts` and `users/{uid}/bots`.
- [ ] **Security**: Implement encryption for sensitive broker credentials stored in Firestore.

## 🚢 Phase 2: Dockerization (Dual-Image Strategy)
- [ ] **macOS Image**: Linux-based Docker with Wine + Xvfb + VNC (optional) for MT5 visibility.
- [ ] **Windows Image**: Optimization for native execution if applicable, or unified Linux/Wine approach.
- [ ] **Environment**: Refactor `.env` handling for dynamic injection during `docker run`.

## 🎨 Phase 3: Premium Onboarding Wizard
- [ ] **Next.js Implementation**: Create `/onboarding` flow.
    - Step 1: Account Connection (MT5 Login, Password, Server).
    - Step 2: Real-time Validation (Backend ping to MT5).
    - Step 3: Default Bot Selection.
    - Step 4: Finish & Launch.
- [ ] **Validation API**: New FastAPI endpoint `POST /validate/connection`.

## 🧠 Phase 4: Integration with ATLAS Gap
- [ ] **Darwinian Weights**: Ensure weights persist per-user in Firebase.
- [ ] **CRO Agent**: Global veto patterns vs. user-specific overrides.
- [ ] **Autoresearch**: Local container branching for strategy evolution.

---

## 📅 Timeline & Milestones
1. **Milestone 1**: Successful MT5 connection validation via API.
2. **Milestone 2**: First "Bot Launch" from the new dashboard.
3. **Milestone 3**: Docker image published and tested on Windows/Mac.
