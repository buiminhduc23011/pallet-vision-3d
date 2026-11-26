import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Alert, App as AntApp, Button, ConfigProvider, Modal, Segmented, Switch, Tag, Tooltip } from 'antd';
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Box,
  Camera,
  Check,
  ChevronRight,
  ClipboardCheck,
  Crosshair,
  FileImage,
  History,
  Layers3,
  LoaderCircle,
  Play,
  RotateCcw,
  ScanLine,
  Settings2,
  ShieldCheck,
  Square,
  Unplug,
} from 'lucide-react';
import { api, awaitJob, post } from './api/client';
import type {
  Calibration,
  Config,
  Frame,
  Health,
  HistoryPage,
  Inspection,
  JobTicket,
  Point,
  Reference,
  ROI,
  Session,
  Verification,
} from './api/types';
import { isSession, useSessionEvents } from './hooks/useSessionEvents';
import InspectionViewport from './components/InspectionViewport';
import HistoryTable from './components/HistoryTable';
const SettingsModal = lazy(() => import('./components/SettingsModal'));
const UploadModal = lazy(() => import('./components/UploadModal'));
const TeachModal = lazy(() => import('./components/TeachModal'));

const format = (value: number | null | undefined, suffix = '') =>
  value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}${suffix}`;

function Workstation() {
  const { message } = AntApp.useApp();
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const configRef = useRef(config);
  configRef.current = config;
  const [session, setSession] = useState<Session | null>(null);
  const sessionRef = useRef(session);
  sessionRef.current = session;
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [reference, setReference] = useState<Reference | null>(null);
  const [verification, setVerification] = useState<Verification | null>(null);
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const [error, setError] = useState('');
  const [settings, setSettings] = useState(false);
  const [teachOpen, setTeachOpen] = useState(false);
  const [teachFrame, setTeachFrame] = useState<Frame | null>(null);
  const [uploadRole, setUploadRole] = useState<string | null>(null);
  const [filename, setFilename] = useState('No file selected');
  const [floorROI, setFloorROI] = useState<ROI | null>(null);
  const [history, setHistory] = useState<HistoryPage>({ items: [], next_cursor: null });
  const [historyFilter, setHistoryFilter] = useState('ALL');
  const [historyDetail, setHistoryDetail] = useState<Verification | null>(null);
  const [capture, setCapture] = useState<Frame | null>(null);
  const [connected, setConnected] = useState(false);

  const report = (err: unknown) => {
    const text = err instanceof Error ? err.message : 'An unexpected error occurred';
    setError(text);
    void message.error(text);
  };
  async function run(work: () => Promise<void>) {
    if (working.current) return;
    working.current = true;
    setBusy(true);
    setError('');
    try {
      await work();
    } catch (err) {
      report(err);
    } finally {
      working.current = false;
      setBusy(false);
    }
  }
  async function loadHistory(filter = historyFilter, cursor?: string) {
    const query = new URLSearchParams({ limit: '10' });
    if (filter !== 'ALL') query.set('verdict', filter);
    if (cursor) query.set('cursor', cursor);
    const result = await api<HistoryPage>(`/history?${query}`);
    setHistory((previous) => ({
      ...result,
      items: cursor ? [...previous.items, ...result.items] : result.items,
    }));
  }
  useEffect(() => {
    let disposed = false;
    void (async () => {
      try {
        const [status, cfg, log] = await Promise.all([
          api<Health>('/health'),
          api<Config>('/config'),
          api<HistoryPage>('/history?limit=10'),
        ]);
        if (disposed) return;
        setHealth(status);
        setConfig(cfg);
        setHistory(log);
        setConnected(true);
        // Camera ownership is explicit: always begin with a safe offline workspace.
        const initial = await post<Session>('/sessions', { mode: 'offline' });
        if (!disposed) setSession(initial);
      } catch (err) {
        if (!disposed) report(err);
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  useSessionEvents(session?.id, (type, payload) => {
    if (type === 'connection.lost') {
      setConnected(false);
      return;
    }
    setConnected(true);
    if ((type === 'heartbeat' || type === 'session.state') && isSession(payload)) {
      setSession(payload);
      return;
    }
    if (type === 'source.disconnected') {
      setError(String(payload.message));
      return;
    }
    if (type === 'reference.invalidated') {
      setReference(null);
      setVerification(null);
      return;
    }
    if (type === 'inspection.completed' && typeof payload.inspection_id === 'string') {
      const sessionId = sessionRef.current?.id;
      void api<Inspection>(`/inspections/${payload.inspection_id}`)
        .then((result) => {
          if (
            sessionRef.current?.id === sessionId &&
            result.config_revision === configRef.current?.revision
          ) {
            setInspection(result);
            setVerification((previous) => (previous?.inspection_id === result.id ? previous : null));
          }
        })
        .catch(report);
    }
    if (type === 'verification.completed' && typeof payload.verification_id === 'string') {
      const sessionId = sessionRef.current?.id;
      void api<Verification>(`/verifications/${payload.verification_id}`)
        .then((result) => {
          if (sessionRef.current?.id === sessionId && result.config_revision === configRef.current?.revision)
            setVerification(result);
          void loadHistory().catch(report);
        })
        .catch(report);
    }
  });

  async function inspectCurrent(active = session, cfg = config) {
    if (!active || !cfg) throw new Error('No active input');
    const frame = await post<Frame>(`/sessions/${active.id}/frames`, {});
    const ticket = await post<JobTicket>('/inspections', {
      frame_id: frame.id,
      config_revision: cfg.revision,
      session_id: active.id,
    });
    const result = await awaitJob<Inspection>(ticket);
    setInspection(result);
    setVerification(null);
    return result;
  }
  async function verifyInspection(result: Inspection, ref = reference, active = session) {
    if (!ref) throw new Error('Load or capture a reference pallet first');
    const ticket = await post<JobTicket>('/verifications', {
      reference_id: ref.id,
      inspection_id: result.id,
      session_id: active?.id,
    });
    const checked = await awaitJob<Verification>(ticket);
    setVerification(checked);
    await loadHistory();
  }
  async function upload(data: FormData, name: string) {
    await run(async () => {
      const asset = await api<{ id: string }>('/assets', { method: 'POST', body: data });
      const active = await post<Session>('/sessions', { mode: 'offline', asset_id: asset.id });
      setSession(active);
      setInspection(null);
      setVerification(null);
      setFilename(name);
      setFloorROI(null);
      if (reference)
        await api(`/sessions/${active.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ reference_id: reference.id }),
        });
      const result = await inspectCurrent(active);
      if (uploadRole === 'Reference image') {
        const ref = await post<Reference>('/references', {
          inspection_id: result.id,
          label: name,
          session_id: active.id,
        });
        setReference(ref);
        void message.success('Reference captured from the loaded image');
      } else if (uploadRole === 'Target image' && reference)
        await verifyInspection(result, reference, active);
      setUploadRole(null);
    });
  }
  async function switchMode(mode: string) {
    if (mode === session?.mode) return;
    await run(async () => {
      const active = await post<Session>('/sessions', { mode });
      setSession(active);
      setInspection(null);
      setVerification(null);
      setFilename('No file selected');
      setFloorROI(null);
      if (reference)
        await api(`/sessions/${active.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ reference_id: reference.id }),
        });
    });
  }
  async function applyConfig(next: Config) {
    let success = false;
    await run(async () => {
      const saved = await api<{ config: Config; reprocessing_job_ids: string[] }>('/config', {
        method: 'PUT',
        headers: { 'If-Match': `"${configRef.current?.revision}"` },
        body: JSON.stringify(next),
      });
      setConfig(saved.config);
      configRef.current = saved.config;
      setInspection(null);
      setVerification(null);
      setReference(null);
      for (const jobId of saved.reprocessing_job_ids)
        await awaitJob({ job_id: jobId, status_url: `/api/v1/jobs/${jobId}` });
      if (sessionRef.current) {
        const state = await api<Session>(`/sessions/${sessionRef.current.id}`);
        setSession(state);
        const [current, ref, checked] = await Promise.all([
          state.inspection_id ? api<Inspection>(`/inspections/${state.inspection_id}`) : null,
          state.reference_id ? api<Reference>(`/references/${state.reference_id}`) : null,
          state.verification_id ? api<Verification>(`/verifications/${state.verification_id}`) : null,
        ]);
        setInspection(current);
        setReference(ref);
        setVerification(checked);
      }
      success = true;
    });
    return success;
  }
  async function confirmOrigin(origin: Point) {
    if (!inspection || !config || !session) return;
    await run(async () => {
      const result = await awaitJob<Inspection>(
        await post<JobTicket>('/inspections', {
          frame_id: inspection.frame_id,
          config_revision: config.revision,
          session_id: session.id,
          confirmed_origin: origin,
        }),
      );
      setInspection(result);
      setVerification(null);
    });
  }
  async function calibrate() {
    if (!session || !config || !floorROI) return;
    let updated: Config | null = null;
    await run(async () => {
      if (!inspection) throw new Error('Inspect and pin a frame before fitting the floor');
      const result = await awaitJob<Calibration>(
        await post<JobTicket>('/calibrations', { frame_id: inspection.frame_id, roi: floorROI }),
      );
      updated = {
        ...config,
        calibration: {
          ...config.calibration,
          id: result.id,
          floor_plane: result.plane,
          intrinsics: result.intrinsics,
          camera_serial: result.camera_serial,
          floor_distance_mm: null,
        },
      };
      void message.success(`Floor plane fitted · residual ${result.rms_mm.toFixed(2)} mm`);
    });
    if (updated) await applyConfig(updated);
  }
  const disabled = busy || (session?.pending_jobs ?? 0) > 0;
  const verdict =
    verification?.verdict ??
    (inspection ? (inspection.state === 'INCOMPLETE' ? 'INCOMPLETE' : inspection.alignment.status) : 'READY');
  const good = verdict === 'PASS' || verdict === 'OK';
  const bad = verdict === 'FAIL' || verdict === 'NG';

  return (
    <div className="app-shell">
      <aside className="side-rail">
        <a href="#" className="brand-mark" aria-label="Pallet Vision home">
          <ScanLine size={25} />
        </a>
        <div className="rail-nav">
          <Tooltip title="Inspection" placement="right">
            <a className="rail-button active" href="#" aria-label="Inspection">
              <Crosshair size={21} />
            </a>
          </Tooltip>
          <Tooltip title="History" placement="right">
            <a className="rail-button" href="#history" aria-label="History">
              <History size={21} />
            </a>
          </Tooltip>
          <Tooltip title="Settings" placement="right">
            <button
              className="rail-button"
              aria-label="Settings"
              disabled={!config}
              onClick={() => setSettings(true)}
            >
              <Settings2 size={21} />
            </button>
          </Tooltip>
        </div>
        <div className="rail-bottom">
          <ShieldCheck size={20} />
          <span>LOCAL</span>
        </div>
      </aside>
      <div className="app-main">
        <header className="app-header">
          <div className="wordmark">
            PALLET<span>VISION</span>
            <span className="edition">RGB-D</span>
          </div>
          <div className="header-status">
            <span>
              <i className={`status-dot ${connected ? 'on' : ''}`} />
              {connected ? 'Engine connected' : 'Engine offline'}
            </span>
            <span className="header-divider" />
            <span>Inspection workstation</span>
            <Button
              aria-label="Open calibration and settings"
              icon={<Settings2 size={16} />}
              disabled={!config}
              onClick={() => setSettings(true)}
            >
              Settings
            </Button>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">QUALITY CONTROL / PALLET TRANSFER</div>
              <h1>
                Inspection workspace<span>.</span>
              </h1>
              <p>See the pallet. Verify the placement. Confirm the transfer.</p>
            </div>
            <div className="mode-switch">
              <span className="control-label">INPUT SOURCE</span>
              <Segmented
                value={session?.mode ?? 'offline'}
                disabled={disabled || !session}
                options={[
                  {
                    value: 'live',
                    label: (
                      <span>
                        <Camera size={15} /> Live camera
                      </span>
                    ),
                  },
                  {
                    value: 'offline',
                    label: (
                      <span>
                        <FileImage size={15} /> Image check
                      </span>
                    ),
                  },
                ]}
                onChange={(v) => void switchMode(v)}
              />
            </div>
          </div>
          {error && (
            <Alert
              className="system-alert"
              type="error"
              showIcon
              closable
              message={error}
              onClose={() => setError('')}
            />
          )}
          {health && !health.detector.model_present && (
            <div className="setup-notice">
              <div>
                <Box size={17} />
                <span>
                  <strong>Segmentation model not configured.</strong> RGB checks are available. Add trusted
                  model weights to enable roll detection and transfer verification.
                </span>
              </div>
              <button onClick={() => setSettings(true)}>
                Configure model <ArrowRight size={14} />
              </button>
            </div>
          )}
          <div className="input-strip">
            <div className="input-label">
              <span className="input-icon">
                {session?.mode === 'live' ? <Camera size={20} /> : <FileImage size={20} />}
              </span>
              <div>
                <strong>{session?.mode === 'live' ? 'Intel RealSense' : 'Offline file inspection'}</strong>
                <span>
                  {session?.mode === 'live'
                    ? session.status === 'ready'
                      ? 'Aligned color + depth acquisition'
                      : session.status
                    : filename}
                </span>
              </div>
            </div>
            {session?.mode !== 'live' ? (
              <div className="input-buttons">
                <Button
                  icon={<FileImage size={15} />}
                  disabled={disabled}
                  onClick={() => setUploadRole('Single image')}
                >
                  Single image
                </Button>
                <Button disabled={disabled} onClick={() => setUploadRole('Reference image')}>
                  Reference image
                </Button>
                <Button disabled={disabled || !reference} onClick={() => setUploadRole('Target image')}>
                  Target image <ArrowRight size={14} />
                </Button>
              </div>
            ) : (
              <div className="input-buttons">
                <Button
                  disabled={disabled || !session.frame}
                  icon={<ArrowDownToLine size={15} />}
                  onClick={() =>
                    void run(async () => {
                      const frame = await post<Frame>(`/sessions/${session.id}/frames`, {});
                      setCapture(await post<Frame>('/captures', { frame_id: frame.id }));
                    })
                  }
                >
                  Capture & save frame
                </Button>
                <Tag color={session.status === 'ready' ? 'green' : 'red'}>{session.status.toUpperCase()}</Tag>
              </div>
            )}
          </div>
          {session?.frame?.source === 'bag' && (
            <div className="bag-controls">
              <span>RECORDING PLAYBACK</span>
              <Button
                size="small"
                icon={session.playback === 'playing' ? <Square size={12} /> : <Play size={12} />}
                onClick={() =>
                  void run(async () =>
                    setSession(
                      await api<Session>(`/sessions/${session.id}`, {
                        method: 'PATCH',
                        body: JSON.stringify({
                          playback: session.playback === 'playing' ? 'paused' : 'playing',
                        }),
                      }),
                    ),
                  )
                }
              >
                {session.playback === 'playing' ? 'Pause' : 'Play'}
              </Button>
              <Button
                size="small"
                onClick={() =>
                  void run(async () => {
                    setSession(
                      await api<Session>(`/sessions/${session.id}`, {
                        method: 'PATCH',
                        body: JSON.stringify({ seek_seconds: 0, playback: 'paused' }),
                      }),
                    );
                  })
                }
              >
                Rewind
              </Button>
              <Button
                size="small"
                disabled={disabled}
                onClick={() =>
                  void run(async () => {
                    await inspectCurrent();
                  })
                }
              >
                Inspect current frame
              </Button>
              <span>{session.status}</span>
            </div>
          )}
          {session?.mode === 'live' && (
            <div className="bag-controls">
              <span>LIVE INSPECTION</span>
              <Button
                size="small"
                disabled={disabled || !session.frame}
                icon={<ScanLine size={14} />}
                onClick={() =>
                  void run(async () => {
                    await inspectCurrent();
                  })
                }
              >
                Inspect & pin frame
              </Button>
              <span>Switch to “Pinned inspection” in the viewport to draw a floor sample.</span>
            </div>
          )}
          <div className="teach-entry">
            <div>
              <strong>PALLET SETUP</strong>
              <span>
                {config?.teaching
                  ? config.teaching.require_origin_confirmation
                    ? 'Taught datum active · confirm origin on each pinned inspection'
                    : 'Taught datum active · axis-only / 180° reversal not verified'
                  : 'No taught datum · exploratory inspection only'}
              </span>
            </div>
            <Button
              disabled={disabled || !config}
              icon={<Crosshair size={16} />}
              onClick={() =>
                void run(async () => {
                  let pinned: Frame | null = null;
                  if (session?.frame) pinned = await post<Frame>(`/sessions/${session.id}/frames`, {});
                  setTeachFrame(pinned);
                  setTeachOpen(true);
                })
              }
            >
              Teach setup / Recipes
            </Button>
          </div>
          <div className="inspection-layout">
            <div className="inspection-main">
              <InspectionViewport
                session={session}
                inspection={inspection}
                verification={verification}
                config={config}
                busy={disabled}
                onUpload={() => setUploadRole('Single image')}
                onOrigin={confirmOrigin}
                onROI={(roi) => {
                  if (config) void applyConfig({ ...config, roi });
                }}
                onFloorROI={(roi) => {
                  setFloorROI(roi);
                  setSettings(true);
                }}
              />
              <div className="reference-strip">
                <div className={`reference-thumb ${reference ? 'has-image' : ''}`}>
                  {reference ? (
                    <img src={reference.image_urls.rgb} alt="Captured reference pallet" />
                  ) : (
                    <Layers3 size={23} />
                  )}
                </div>
                <div>
                  <span className="control-label">REFERENCE PALLET</span>
                  <strong>{reference?.label ?? 'No reference captured'}</strong>
                  <span>
                    {reference
                      ? `${reference.rolls.length} rolls · ${reference.scope} · configuration ${reference.config_revision}`
                      : 'Capture or load the old pallet before verifying a transfer.'}
                  </span>
                </div>
                {reference && (
                  <Tag color="green">
                    <Check size={12} /> Stored
                  </Tag>
                )}
                <div className="reference-step">
                  A <ChevronRight size={16} /> B
                </div>
              </div>
            </div>
            <aside className="results-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-index">02</span>
                  <h2>Inspection results</h2>
                </div>
                <Activity size={17} />
              </div>
              <div className={`verdict-block ${good ? 'good' : bad ? 'bad' : ''}`}>
                <div className="verdict-caption">
                  <span>{verification ? 'TRANSFER VERDICT' : 'INSPECTION STATUS'}</span>
                  {disabled && <LoaderCircle size={15} className="spin" />}
                </div>
                <div className="verdict-value">
                  {disabled ? 'PROCESSING' : verdict === 'READY' ? 'STANDBY' : verdict}
                </div>
                <p>
                  {disabled
                    ? 'Analyzing the real input frame…'
                    : verification
                      ? `${verification.matched_count} of ${verification.reference_count} reference rolls matched`
                      : inspection?.state === 'INCOMPLETE'
                        ? 'Required evidence is missing. No pass issued.'
                        : inspection
                          ? 'Placement evaluation complete. Transfer check is separate.'
                          : 'Load an input to begin inspection.'}
                </p>
              </div>
              <div className="result-section">
                <div className="result-title">
                  <span>PALLET MATERIAL</span>
                  <Box size={15} />
                </div>
                <div className="material-result">
                  <strong>{inspection?.classification.material ?? '—'}</strong>
                  <span>
                    {inspection
                      ? `${(inspection.classification.confidence * 100).toFixed(0)}% score`
                      : 'Not evaluated'}
                  </span>
                </div>
                <div className="confidence-track">
                  <i style={{ width: `${(inspection?.classification.confidence ?? 0) * 100}%` }} />
                </div>
              </div>
              <div className="result-section">
                <div className="result-title">
                  <span>PLACEMENT / ALIGNMENT</span>
                  <Tag>{inspection?.alignment.unit ?? 'px / mm'}</Tag>
                </div>
                <div className="alignment-grid">
                  <div>
                    <span>Δ X</span>
                    <strong>{format(inspection?.alignment.dx)}</strong>
                  </div>
                  <div>
                    <span>Δ Y</span>
                    <strong>{format(inspection?.alignment.dy)}</strong>
                  </div>
                  <div>
                    <span>Δ θ</span>
                    <strong>{format(inspection?.alignment.angle_deg, '°')}</strong>
                  </div>
                </div>
                <div className="alignment-note">
                  {inspection?.alignment.reasons.length
                    ? inspection.alignment.reasons.join(' · ')
                    : inspection
                      ? inspection.alignment.method.replaceAll('_', ' ')
                      : 'Position and rotation relative to the target zone'}
                </div>
              </div>
              <div className="result-section transfer-section">
                <div className="result-title">
                  <span>TRANSFER VERIFICATION</span>
                  <ClipboardCheck size={15} />
                </div>
                <div className="count-line">
                  <span>Roll count</span>
                  <strong>
                    {verification
                      ? `${verification.current_count} / ${verification.reference_count}`
                      : inspection
                        ? `${inspection.rolls.length} / ${reference?.rolls.length ?? '—'}`
                        : '— / —'}
                    <small>current / reference</small>
                  </strong>
                </div>
                <div className="transfer-grid">
                  <div>
                    <i className="dot green" />
                    Matched<strong>{verification?.matched_count ?? '—'}</strong>
                  </div>
                  <div>
                    <i className="dot red" />
                    Missing<strong>{verification?.missing_count ?? '—'}</strong>
                  </div>
                  <div>
                    <i className="dot orange" />
                    Mismatch<strong>{verification?.mismatch_count ?? '—'}</strong>
                  </div>
                  <div>
                    <i className="dot blue" />
                    Extra<strong>{verification?.extra_count ?? '—'}</strong>
                  </div>
                </div>
                {verification?.reasons.length ? (
                  <p className="qc-reasons">{verification.reasons.join(' · ')}</p>
                ) : null}
              </div>
              {inspection?.warnings.length ? (
                <div className="inspection-warnings">
                  {inspection.warnings.map((w) => (
                    <p key={w.code}>{w.message}</p>
                  ))}
                </div>
              ) : null}
              <div className="inspection-actions">
                <Button
                  block
                  disabled={disabled || !session?.frame}
                  icon={<Crosshair size={16} />}
                  onClick={() =>
                    void run(async () => {
                      const result =
                        session?.mode === 'live' || !inspection ? await inspectCurrent() : inspection;
                      setReference(
                        await post<Reference>('/references', {
                          inspection_id: result.id,
                          label: session?.mode === 'live' ? 'Live reference pallet' : filename,
                          session_id: session?.id,
                        }),
                      );
                      void message.success('Reference snapshot stored');
                    })
                  }
                >
                  Capture reference
                </Button>
                <Button
                  block
                  type="primary"
                  disabled={disabled || !reference || !session?.frame}
                  icon={<ShieldCheck size={17} />}
                  onClick={() =>
                    void run(async () => {
                      const result =
                        session?.mode === 'live' || !inspection ? await inspectCurrent() : inspection;
                      await verifyInspection(result);
                    })
                  }
                >
                  Verify transfer <ArrowRight size={15} />
                </Button>
                <div className="secondary-actions">
                  <Button
                    disabled={disabled || !session?.frame}
                    icon={<ArrowDownToLine size={14} />}
                    onClick={() =>
                      void run(async () => {
                        if (!session) return;
                        const frame = await post<Frame>(`/sessions/${session.id}/frames`, {});
                        setCapture(await post<Frame>('/captures', { frame_id: frame.id }));
                      })
                    }
                  >
                    Save snapshot
                  </Button>
                  <Button
                    disabled={disabled}
                    icon={<RotateCcw size={14} />}
                    onClick={() =>
                      void run(async () => {
                        if (!session) return;
                        setSession(await post<Session>(`/sessions/${session.id}/reset`, {}));
                        setInspection(null);
                        setVerification(null);
                        setReference(null);
                      })
                    }
                  >
                    Reset
                  </Button>
                </div>
                <div className="continuous-control">
                  <span>Continuous transfer check</span>
                  <Switch
                    size="small"
                    aria-label="Continuous transfer check"
                    disabled={disabled || session?.mode !== 'live' || !reference}
                    checked={session?.continuous ?? false}
                    onChange={(continuous) =>
                      void run(async () => {
                        if (session)
                          setSession(
                            await api<Session>(`/sessions/${session.id}`, {
                              method: 'PATCH',
                              body: JSON.stringify({ continuous }),
                            }),
                          );
                      })
                    }
                  />
                </div>
              </div>
            </aside>
          </div>
          <HistoryTable
            items={history.items}
            next={history.next_cursor}
            busy={disabled}
            filter={historyFilter}
            onFilter={(value) => {
              setHistoryFilter(value);
              void loadHistory(value).catch(report);
            }}
            onRefresh={() => void loadHistory().catch(report)}
            onMore={() => {
              if (history.next_cursor) void loadHistory(historyFilter, history.next_cursor).catch(report);
            }}
            onOpen={setHistoryDetail}
          />
          <footer className="page-footer">
            <span>
              <ShieldCheck size={13} /> Local processing. Real evidence. Traceable decisions.
            </span>
            <span>
              {health?.camera.devices.length ? (
                'RealSense available'
              ) : (
                <>
                  <Unplug size={13} /> No camera connected
                </>
              )}
              <span className="footer-separator">/</span>ENGINE {health?.version ?? '—'}
            </span>
          </footer>
        </main>
      </div>
      <Suspense fallback={null}>
        {teachOpen && config && (
          <TeachModal
            frame={teachFrame}
            config={config}
            onClose={() => setTeachOpen(false)}
            onApply={applyConfig}
          />
        )}
        {settings && config && (
          <SettingsModal
            config={config}
            busy={disabled}
            floorROI={floorROI}
            onClose={() => setSettings(false)}
            onSave={async (next) => {
              await applyConfig(next);
            }}
            onCalibrate={calibrate}
          />
        )}
        {uploadRole && (
          <UploadModal
            role={uploadRole}
            busy={disabled}
            onClose={() => {
              if (!busy) setUploadRole(null);
            }}
            onSubmit={(data, name) => void upload(data, name)}
          />
        )}
      </Suspense>
      <Modal
        open={!!capture}
        title="Frame saved to this workstation"
        onCancel={() => setCapture(null)}
        footer={<Button onClick={() => setCapture(null)}>Done</Button>}
      >
        <p>
          Lossless source data and camera metadata are stored under <code>data/captures/{capture?.id}/</code>.
        </p>
        <div className="download-links">
          {capture?.image_urls &&
            Object.entries(capture.image_urls).map(([kind, url]) => (
              <a key={kind} href={url} target="_blank" rel="noreferrer">
                <ArrowDownToLine size={15} />
                {kind.replaceAll('_', ' ')}
              </a>
            ))}
        </div>
      </Modal>
      <Modal
        open={!!historyDetail}
        width={1000}
        title={historyDetail ? `Verification QC-${historyDetail.id.slice(0, 8).toUpperCase()}` : ''}
        onCancel={() => setHistoryDetail(null)}
        footer={<Button onClick={() => setHistoryDetail(null)}>Close</Button>}
      >
        {historyDetail && (
          <>
            <div className="history-detail-summary">
              <Tag color={historyDetail.verdict === 'PASS' ? 'green' : 'gold'}>{historyDetail.verdict}</Tag>
              <span>
                {new Date(historyDetail.created_at).toLocaleString()} · {historyDetail.scope} · Config{' '}
                {historyDetail.config_revision}
              </span>
            </div>
            <div className="history-images">
              <figure>
                <img src={historyDetail.reference_image_url} alt="Original reference pallet" />
                <figcaption>Reference pallet</figcaption>
              </figure>
              <figure>
                <img src={historyDetail.overlay_url} alt="Saved transfer difference overlay" />
                <figcaption>Target · saved difference overlay</figcaption>
              </figure>
            </div>
            <p>{historyDetail.reasons.join(' · ')}</p>
            <div className="history-pairs">
              {historyDetail.pairs.map((pair) => (
                <div key={pair.reference_roll_id}>
                  {pair.reference_roll_id} → {pair.current_roll_id}
                  <Tag color={pair.reasons.length ? 'orange' : 'green'}>
                    {pair.reasons.join(', ') || 'MATCHED'}
                  </Tag>
                </div>
              ))}
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}

export default function App() {
  return (
    <ConfigProvider
      theme={{
        token: {
          colorPrimary: '#0c7569',
          colorInfo: '#0c7569',
          borderRadius: 5,
          fontFamily: 'IBM Plex Sans, sans-serif',
          colorText: '#233538',
          colorBorder: '#d9e0df',
          controlHeight: 36,
        },
        components: {
          Button: { primaryShadow: 'none' },
          Segmented: { itemSelectedBg: '#ffffff', trackBg: '#e4eae9' },
        },
      }}
    >
      <AntApp>
        <Workstation />
      </AntApp>
    </ConfigProvider>
  );
}
