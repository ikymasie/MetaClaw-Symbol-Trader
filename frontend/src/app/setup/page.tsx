'use client';

import { useState } from 'react';
import { useSetup, type SetupStep } from '@/hooks/useSetup';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Progress } from '@/components/ui/progress';
import {
  Database, KeyRound, Users, CheckCircle2, Loader2, AlertTriangle,
  ArrowRight, ArrowLeft, Plus, Trash2, TestTube, Eye, EyeOff,
  Server, Wifi, WifiOff, Sparkles, Shield, Settings, Home,
} from 'lucide-react';

const STEP_META: Record<SetupStep, { icon: React.ElementType; title: string; desc: string }> = {
  database:   { icon: Database,     title: 'Database',       desc: 'Connect your Neon PostgreSQL' },
  accounts:   { icon: Users,        title: 'MT5 Accounts',   desc: 'Add broker credentials' },
  'api-keys': { icon: KeyRound,     title: 'API Keys',       desc: 'Gemini & Alpaca keys' },
  complete:   { icon: CheckCircle2, title: 'Launch',         desc: 'Review & start trading' },
};
const STEPS: SetupStep[] = ['database', 'accounts', 'api-keys', 'complete'];

export default function SetupPage() {
  const setup = useSetup();

  if (setup.loading) {
    return (
      <div className="flex items-center justify-center min-h-[80vh]">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    );
  }

  if (setup.status?.setup_complete) {
    return <SettingsPanel setup={setup} />;
  }

  const progress = ((setup.stepIndex + 1) / STEPS.length) * 100;

  return (
    <main className="min-h-[calc(100vh-4rem)] flex items-start justify-center py-10 px-4">
      <div className="w-full max-w-2xl space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-primary to-[oklch(72.3%_0.15_150)] bg-clip-text text-transparent">
            TradeClaw Setup
          </h1>
          <p className="text-muted-foreground">Configure your trading engine in 4 steps</p>
        </div>

        {/* Step Indicators */}
        <div className="flex items-center gap-2">
          {STEPS.map((s, i) => {
            const meta = STEP_META[s];
            const Icon = meta.icon;
            const isActive = s === setup.step;
            const isDone = i < setup.stepIndex;
            return (
              <button key={s} onClick={() => setup.goToStep(s)}
                className={`flex-1 flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-medium transition-all
                  ${isActive ? 'bg-primary/15 text-primary ring-1 ring-primary/30' : ''}
                  ${isDone ? 'text-success' : ''}
                  ${!isActive && !isDone ? 'text-muted-foreground hover:bg-muted/50' : ''}
                `}>
                <Icon className="w-4 h-4 shrink-0" />
                <span className="hidden sm:inline">{meta.title}</span>
              </button>
            );
          })}
        </div>
        <Progress value={progress} className="h-1" />

        {/* Error Banner */}
        {setup.error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{setup.error}</AlertDescription>
          </Alert>
        )}

        {/* Step Content */}
        {setup.step === 'database'   && <DatabaseStep setup={setup} />}
        {setup.step === 'accounts'   && <AccountsStep setup={setup} />}
        {setup.step === 'api-keys'   && <ApiKeysStep setup={setup} />}
        {setup.step === 'complete'   && <CompleteStep setup={setup} />}
      </div>
    </main>
  );
}

/* ═══════════════════════════════════════════════════════════
 * Step 1: Database
 * ═══════════════════════════════════════════════════════════ */
function DatabaseStep({ setup }: { setup: ReturnType<typeof useSetup> }) {
  const [url, setUrl] = useState('');

  const handleTest = () => { if (url.trim()) setup.testDatabase(url.trim()); };
  const handleSave = async () => {
    if (url.trim() && (await setup.saveDatabase(url.trim()))) setup.nextStep();
  };

  return (
    <Card className="glass border-border/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Database className="w-5 h-5 text-primary" /> PostgreSQL Connection</CardTitle>
        <CardDescription>Paste your Neon database URL. We&apos;ll test it before saving.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="db-url">Connection String</Label>
          <Input id="db-url" placeholder="postgresql://user:pass@host/dbname?sslmode=require"
            value={url} onChange={e => setUrl(e.target.value)} className="font-mono text-sm" />
        </div>

        {setup.dbTestResult && (
          <Alert variant={setup.dbTestResult.connected ? 'default' : 'destructive'}>
            {setup.dbTestResult.connected ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />}
            <AlertDescription className="text-sm">{setup.dbTestResult.message}</AlertDescription>
          </Alert>
        )}

        <div className="flex gap-2 justify-end">
          <Button variant="outline" onClick={handleTest} disabled={!url.trim() || setup.testingDb}>
            {setup.testingDb ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <TestTube className="w-4 h-4 mr-1" />}
            Test
          </Button>
          <Button onClick={handleSave} disabled={!url.trim()}>
            Save & Continue <ArrowRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* ═══════════════════════════════════════════════════════════
 * Step 2: MT5 Accounts
 * ═══════════════════════════════════════════════════════════ */
function AccountsStep({ setup }: { setup: ReturnType<typeof useSetup> }) {
  const [showForm, setShowForm] = useState(setup.accounts.length === 0);
  const [label, setLabel] = useState('');
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [server, setServer] = useState('');
  const [showPw, setShowPw] = useState(false);

  const handleAdd = async () => {
    const ok = await setup.addAccount({
      label: label || `Account ${setup.accounts.length + 1}`,
      mt5_login: parseInt(login, 10),
      mt5_password: password,
      mt5_server: server,
      is_default: setup.accounts.length === 0,
    });
    if (ok) { setLabel(''); setLogin(''); setPassword(''); setServer(''); setShowForm(false); }
  };

  return (
    <Card className="glass border-border/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Users className="w-5 h-5 text-primary" /> MT5 Broker Accounts</CardTitle>
        <CardDescription>Add at least one MetaTrader 5 account. AutoTrading must be enabled.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Existing accounts */}
        {setup.accounts.map(acct => (
          <div key={acct.id} className="flex items-center gap-3 p-3 rounded-lg bg-muted/30 border border-border/30">
            <Server className="w-5 h-5 text-muted-foreground shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-medium text-sm truncate">{acct.label}</p>
              <p className="text-xs text-muted-foreground">{acct.mt5_server} · Login {acct.mt5_login}</p>
            </div>
            {acct.is_default && <Badge variant="secondary" className="text-xs">Default</Badge>}
            <Button size="sm" variant="ghost" className="text-destructive h-8 w-8 p-0"
              onClick={() => setup.removeAccount(acct.id)}>
              <Trash2 className="w-4 h-4" />
            </Button>
          </div>
        ))}

        {/* Add form */}
        {showForm ? (
          <div className="space-y-3 p-4 rounded-lg border border-dashed border-primary/30 bg-primary/5">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Label</Label>
                <Input placeholder="My Broker" value={label} onChange={e => setLabel(e.target.value)} />
              </div>
              <div className="space-y-1">
                <Label className="text-xs">Server</Label>
                <Input placeholder="MetaQuotes-Demo" value={server} onChange={e => setServer(e.target.value)} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <Label className="text-xs">Login (number)</Label>
                <Input type="number" placeholder="12345678" value={login} onChange={e => setLogin(e.target.value)} />
              </div>
              <div className="space-y-1 relative">
                <Label className="text-xs">Password</Label>
                <div className="relative">
                  <Input type={showPw ? 'text' : 'password'} value={password} onChange={e => setPassword(e.target.value)} className="pr-9" />
                  <button className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground" onClick={() => setShowPw(!showPw)}>
                    {showPw ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              {setup.accounts.length > 0 && (
                <Button variant="ghost" size="sm" onClick={() => setShowForm(false)}>Cancel</Button>
              )}
              <Button size="sm" onClick={handleAdd} disabled={!login || !password || !server || setup.addingAccount}>
                {setup.addingAccount ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Plus className="w-4 h-4 mr-1" />}
                Connect & Add
              </Button>
            </div>
          </div>
        ) : (
          <Button variant="outline" className="w-full border-dashed" onClick={() => setShowForm(true)}>
            <Plus className="w-4 h-4 mr-1" /> Add Another Account
          </Button>
        )}

        {/* Navigation */}
        <div className="flex justify-between pt-2">
          <Button variant="ghost" onClick={setup.prevStep}><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
          <Button onClick={setup.nextStep} disabled={setup.accounts.length === 0}>
            Continue <ArrowRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* ═══════════════════════════════════════════════════════════
 * Step 3: API Keys + Model Selection
 * ═══════════════════════════════════════════════════════════ */
const GEMINI_MODELS = [
  { id: 'gemini-3.1-flash',              label: 'Gemini 3.1 Flash' },
  { id: 'gemini-3.1-flash-lite',         label: 'Gemini 3.1 Flash Lite (Fast)' },
];

function ApiKeysStep({ setup }: { setup: ReturnType<typeof useSetup> }) {
  const [geminiKey, setGeminiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState('gemini-3.1-flash-lite');
  const [alpacaKey, setAlpacaKey] = useState('');
  const [showKeys, setShowKeys] = useState(false);
  const [saved, setSaved] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSave = async () => {
    setLocalError(null);
    setSaved(false);

    const keys: Record<string, string> = {};
    if (geminiKey.trim()) keys.gemini_api_key = geminiKey.trim();
    if (alpacaKey.trim()) keys.alpaca_news_api_key = alpacaKey.trim();
    // Always include model selection
    keys.gemini_model = geminiModel;

    if (!geminiKey.trim() && !alpacaKey.trim()) {
      // Skip but still save model preference
      try {
        await setup.saveApiKeys({ gemini_model: geminiModel });
      } catch { /* non-critical */ }
      setup.nextStep();
      return;
    }

    const ok = await setup.saveApiKeys(keys);
    if (ok) {
      setSaved(true);
      setTimeout(() => setup.nextStep(), 600);
    } else {
      setLocalError(setup.error || 'Failed to save API keys. Check your backend logs.');
    }
  };

  return (
    <Card className="glass border-border/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><KeyRound className="w-5 h-5 text-primary" /> API Keys & Model</CardTitle>
        <CardDescription>Configure your AI model and optional API keys for brain analysis and news sentiment.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Model Selection */}
        <div className="space-y-2">
          <Label htmlFor="gemini-model" className="flex items-center gap-1">
            <Sparkles className="w-3.5 h-3.5" /> Gemini Model
          </Label>
          <select
            id="gemini-model"
            value={geminiModel}
            onChange={e => setGeminiModel(e.target.value)}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
          >
            {GEMINI_MODELS.map(m => (
              <option key={m.id} value={m.id}>{m.label}</option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">
            Controls the AI brain that analyzes your trades and suggests parameter adjustments.
          </p>
        </div>

        {/* Gemini API Key */}
        <div className="space-y-2">
          <Label htmlFor="gemini-key" className="flex items-center gap-1">
            <Sparkles className="w-3.5 h-3.5" /> Gemini API Key
          </Label>
          <Input id="gemini-key" type={showKeys ? 'text' : 'password'}
            placeholder="AIza..." value={geminiKey} onChange={e => setGeminiKey(e.target.value)} />
          <p className="text-xs text-muted-foreground">Get one free at <a href="https://aistudio.google.com/apikey" target="_blank" rel="noreferrer" className="text-primary underline">Google AI Studio</a></p>
        </div>

        {/* Alpaca API Key */}
        <div className="space-y-2">
          <Label htmlFor="alpaca-key" className="flex items-center gap-1">
            <Shield className="w-3.5 h-3.5" /> Alpaca News API Key
          </Label>
          <Input id="alpaca-key" type={showKeys ? 'text' : 'password'}
            placeholder="PK..." value={alpacaKey} onChange={e => setAlpacaKey(e.target.value)} />
        </div>

        {/* Show/hide toggle */}
        <button className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
          onClick={() => setShowKeys(!showKeys)}>
          {showKeys ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
          {showKeys ? 'Hide' : 'Show'} keys
        </button>

        {/* Feedback */}
        {localError && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription className="text-sm">{localError}</AlertDescription>
          </Alert>
        )}
        {saved && (
          <Alert>
            <CheckCircle2 className="h-4 w-4" />
            <AlertDescription className="text-sm">API keys saved successfully!</AlertDescription>
          </Alert>
        )}

        <div className="flex justify-between pt-2">
          <Button variant="ghost" onClick={setup.prevStep}><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
          <Button onClick={handleSave} disabled={setup.savingKeys}>
            {setup.savingKeys && <Loader2 className="w-4 h-4 animate-spin mr-1" />}
            {geminiKey || alpacaKey ? 'Save & Continue' : 'Skip'}
            <ArrowRight className="w-4 h-4 ml-1" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* ═══════════════════════════════════════════════════════════
 * Step 4: Review & Launch
 * ═══════════════════════════════════════════════════════════ */
function CompleteStep({ setup }: { setup: ReturnType<typeof useSetup> }) {
  const checks = [
    { label: 'Database connected', ok: setup.status?.has_database },
    { label: `${setup.status?.account_count ?? 0} MT5 account(s)`, ok: setup.status?.has_accounts },
    { label: 'API keys configured', ok: setup.status?.has_api_keys },
  ];

  return (
    <Card className="glass border-border/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><CheckCircle2 className="w-5 h-5 text-success" /> Ready to Launch</CardTitle>
        <CardDescription>Review your configuration and start TradeClaw.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          {checks.map(c => (
            <div key={c.label} className="flex items-center gap-2 text-sm">
              {c.ok
                ? <CheckCircle2 className="w-4 h-4 text-success" />
                : <AlertTriangle className="w-4 h-4 text-warning" />}
              <span className={c.ok ? '' : 'text-muted-foreground'}>{c.label}</span>
            </div>
          ))}
        </div>

        <div className="flex justify-between pt-4">
          <Button variant="ghost" onClick={setup.prevStep}><ArrowLeft className="w-4 h-4 mr-1" /> Back</Button>
          <Button size="lg" onClick={setup.completeSetup} disabled={setup.completing || !setup.status?.has_database || !setup.status?.has_accounts}
            className="bg-gradient-to-r from-primary to-[oklch(72.3%_0.15_150)] text-white shadow-lg">
            {setup.completing ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Sparkles className="w-4 h-4 mr-2" />}
            Launch TradeClaw
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

/* ═══════════════════════════════════════════════════════════
 * Settings Panel (Post-Setup Management)
 * ═══════════════════════════════════════════════════════════ */
function SettingsPanel({ setup }: { setup: ReturnType<typeof useSetup> }) {
  const [activeTab, setActiveTab] = useState<'accounts' | 'api-keys' | 'database'>('accounts');

  const tabs = [
    { id: 'accounts'  as const, label: 'MT5 Accounts',   icon: Users,    count: setup.status?.account_count },
    { id: 'api-keys'  as const, label: 'API Keys',       icon: KeyRound, count: undefined },
    { id: 'database'  as const, label: 'Database',       icon: Database, count: undefined },
  ];

  return (
    <main className="min-h-[calc(100vh-4rem)] flex items-start justify-center py-10 px-4">
      <div className="w-full max-w-2xl space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Settings className="w-5 h-5 text-primary" />
              <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
            </div>
            <p className="text-sm text-muted-foreground">
              Manage your TradeClaw configuration
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={() => window.location.href = '/'}>
            <Home className="w-4 h-4 mr-1" /> Dashboard
          </Button>
        </div>

        {/* Status Banner */}
        <div className="flex items-center gap-3 p-3 rounded-lg bg-success/10 border border-success/20">
          <CheckCircle2 className="w-5 h-5 text-success shrink-0" />
          <div className="flex-1">
            <p className="text-sm font-medium">System Active</p>
            <p className="text-xs text-muted-foreground">
              {setup.status?.account_count ?? 0} MT5 account(s) · Database connected ·
              {setup.status?.has_api_keys ? ' API keys configured' : ' No API keys'}
            </p>
          </div>
        </div>

        {/* Tab Bar */}
        <div className="flex gap-1 p-1 rounded-lg bg-muted/30 border border-border/30">
          {tabs.map(tab => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md text-xs font-medium transition-all ${
                  activeTab === tab.id
                    ? 'bg-background text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                {tab.label}
                {tab.count !== undefined && (
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">{tab.count}</Badge>
                )}
              </button>
            );
          })}
        </div>

        {/* Error Banner */}
        {setup.error && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription>{setup.error}</AlertDescription>
          </Alert>
        )}

        {/* Tab Content */}
        {activeTab === 'accounts'  && <AccountsStep setup={setup} />}
        {activeTab === 'api-keys'  && <ApiKeysStep setup={setup} />}
        {activeTab === 'database'  && <SettingsDatabaseTab setup={setup} />}
      </div>
    </main>
  );
}

/* ═══════════════════════════════════════════════════════════
 * Settings: Database Tab
 * ═══════════════════════════════════════════════════════════ */
function SettingsDatabaseTab({ setup }: { setup: ReturnType<typeof useSetup> }) {
  const [url, setUrl] = useState('');
  const [saved, setSaved] = useState(false);

  const handleTest = () => { if (url.trim()) setup.testDatabase(url.trim()); };
  const handleSave = async () => {
    if (url.trim() && (await setup.saveDatabase(url.trim()))) {
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    }
  };

  return (
    <Card className="glass border-border/50">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Database className="w-5 h-5 text-primary" />
          PostgreSQL Connection
        </CardTitle>
        <CardDescription>
          {setup.status?.has_database
            ? 'Database is connected. Enter a new URL below to change it.'
            : 'Paste your Neon database URL.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {setup.status?.has_database && (
          <div className="flex items-center gap-2 text-sm text-success">
            <Wifi className="w-4 h-4" />
            <span>Currently connected</span>
          </div>
        )}

        <div className="space-y-2">
          <Label htmlFor="db-url-settings">New Connection String</Label>
          <Input id="db-url-settings" placeholder="postgresql://user:pass@host/dbname?sslmode=require"
            value={url} onChange={e => setUrl(e.target.value)} className="font-mono text-sm" />
        </div>

        {setup.dbTestResult && (
          <Alert variant={setup.dbTestResult.connected ? 'default' : 'destructive'}>
            {setup.dbTestResult.connected ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />}
            <AlertDescription className="text-sm">{setup.dbTestResult.message}</AlertDescription>
          </Alert>
        )}

        {saved && (
          <Alert>
            <CheckCircle2 className="h-4 w-4" />
            <AlertDescription className="text-sm">Database URL updated successfully.</AlertDescription>
          </Alert>
        )}

        <div className="flex gap-2 justify-end">
          <Button variant="outline" onClick={handleTest} disabled={!url.trim() || setup.testingDb}>
            {setup.testingDb ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <TestTube className="w-4 h-4 mr-1" />}
            Test
          </Button>
          <Button onClick={handleSave} disabled={!url.trim()}>
            Update Database
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
