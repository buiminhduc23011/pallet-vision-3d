import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Input, InputNumber, Modal, Select, Slider, Tabs } from 'antd';
import type { Config, HSVRange, ROI } from '../api/types';

type Props = {
  config: Config;
  busy: boolean;
  floorROI: ROI | null;
  onClose: () => void;
  onSave: (config: Config) => Promise<void>;
  onCalibrate: () => Promise<void>;
};

export default function SettingsModal({ config, busy, floorROI, onClose, onSave, onCalibrate }: Props) {
  const [draft, setDraft] = useState<Config>(config);
  const [advanced, setAdvanced] = useState(JSON.stringify(config, null, 2));
  const [jsonError, setJsonError] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const dirty = useRef(false);
  useEffect(() => {
    setDraft(config);
    setAdvanced(JSON.stringify(config, null, 2));
    dirty.current = false;
  }, [config]);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  function change(next: Config) {
    setDraft(next);
    dirty.current = true;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      dirty.current = false;
      void onSave(next);
    }, 650);
  }
  function close() {
    if (timer.current) clearTimeout(timer.current);
    if (dirty.current && !busy) void onSave(draft);
    onClose();
  }
  function number<K extends Exclude<keyof Config, 'teaching'>>(
    section: K,
    key: keyof Config[K],
    label: string,
    min: number,
    max?: number,
    step = 1,
  ) {
    const value = draft[section][key];
    return (
      <label className="setting-field" key={String(key)}>
        <span>{label}</span>
        <InputNumber
          aria-label={label}
          value={typeof value === 'number' ? value : null}
          min={min}
          max={max}
          step={step}
          disabled={busy}
          onChange={(v) => {
            if (v !== null) change({ ...draft, [section]: { ...(draft[section] as object), [key]: v } });
          }}
        />
      </label>
    );
  }
  function hsv(material: 'wood' | 'plastic', index: number, label: string) {
    const range = draft.classifier[material][index];
    return (
      <div className="hsv-block" key={`${material}-${index}`}>
        <h4>
          <i className={`material-swatch ${material}-${index}`} />
          {label}
        </h4>
        {(['Hue', 'Saturation', 'Value'] as const).map((name, channel) => (
          <div className="hsv-slider" key={name}>
            <span>{name}</span>
            <Slider
              range
              min={0}
              max={channel === 0 ? 179 : 255}
              disabled={busy}
              value={[range.low[channel], range.high[channel]]}
              onChange={(v) => {
                const updated: HSVRange = { low: [...range.low], high: [...range.high] };
                updated.low[channel] = v[0];
                updated.high[channel] = v[1];
                const ranges = [...draft.classifier[material]];
                ranges[index] = updated;
                change({ ...draft, classifier: { ...draft.classifier, [material]: ranges } });
              }}
            />
            <code>
              {range.low[channel]} – {range.high[channel]}
            </code>
          </div>
        ))}
      </div>
    );
  }
  const tabs = [
    {
      key: 'detector',
      label: 'Roll detector',
      children: (
        <div className="settings-stack">
          <Alert
            type="info"
            showIcon
            message="Models are loaded from your trusted local models/ folder."
            description="FastSAM provides shape-filtered candidates. Validate with real pallets before accepting production QC results."
          />
          <label className="setting-field">
            <span>Segmentation backend</span>
            <Select
              aria-label="Segmentation backend"
              disabled={busy}
              value={draft.detector.backend}
              options={[
                { value: 'fastsam', label: 'FastSAM · zero-shot' },
                { value: 'yolo', label: 'Custom YOLO-seg' },
              ]}
              onChange={(v) => change({ ...draft, detector: { ...draft.detector, backend: v } })}
            />
          </label>
          <label className="setting-field">
            <span>Model path (relative to models/)</span>
            <Input
              aria-label="Model path"
              disabled={busy}
              value={draft.detector.model_path}
              onChange={(e) =>
                change({ ...draft, detector: { ...draft.detector, model_path: e.target.value } })
              }
            />
          </label>
          <label className="setting-field">
            <span>Inference device</span>
            <Select
              aria-label="Inference device"
              disabled={busy}
              value={draft.detector.device}
              options={[
                { value: 'cpu', label: 'CPU' },
                { value: '0', label: 'CUDA GPU 0' },
              ]}
              onChange={(v) => change({ ...draft, detector: { ...draft.detector, device: v } })}
            />
          </label>
          <div className="settings-grid">
            {number('detector', 'confidence', 'Confidence threshold', 0.01, 1, 0.05)}
            {number('detector', 'image_size', 'Inference size (px)', 128, 2048, 32)}
            {number('detector', 'min_area_px', 'Minimum mask area (px²)', 1)}
            {number('detector', 'max_area_px', 'Maximum mask area (px²)', 1)}
            {number('detector', 'max_aspect_ratio', 'Maximum aspect ratio', 1, 30, 0.1)}
            {number('detector', 'min_circularity', 'Minimum circularity', 0, 1, 0.05)}
            {number('detector', 'standing_circularity', 'Standing circularity', 0, 1, 0.05)}
            {number('detector', 'depth_valid_fraction', 'Minimum valid depth fraction', 0.01, 1, 0.05)}
          </div>
        </div>
      ),
    },
    {
      key: 'material',
      label: 'Material / HSV',
      children: (
        <div className="settings-stack">
          <p className="settings-help">
            HSV uses OpenCV ranges: H 0–179, S/V 0–255. Changes re-run the loaded real image and reference.
          </p>
          {draft.classifier.wood.map((_, i) => hsv('wood', i, `Wood ${i + 1} · brown / beige`))}
          {draft.classifier.plastic.map((_, i) =>
            hsv('plastic', i, `Plastic ${i + 1} · ${['blue', 'green', 'black'][i] ?? 'custom'}`),
          )}
          <div className="settings-grid">
            {number('classifier', 'minimum_coverage', 'Minimum coverage', 0, 1, 0.05)}
            {number('classifier', 'minimum_margin', 'Minimum class margin', 0, 1, 0.02)}
          </div>
        </div>
      ),
    },
    {
      key: 'calibration',
      label: 'Calibration / ROI',
      children: (
        <div className="settings-stack">
          <Alert
            type="warning"
            showIcon
            message="Depth is not height above the floor."
            description="Draw a floor sample in the viewport, fit the plane, then inspect. A scalar floor distance is valid only for a camera perpendicular to the floor."
          />
          <Button disabled={!floorROI || busy} loading={busy} onClick={() => void onCalibrate()}>
            Fit plane from selected floor sample
          </Button>
          <div className="calibration-readout">
            <span>Plane calibration</span>
            <code>{draft.calibration.id ? draft.calibration.id.slice(0, 12) : 'NOT CALIBRATED'}</code>
          </div>
          <Checkbox
            checked={draft.calibration.perpendicular_camera}
            disabled={busy}
            onChange={(e) =>
              change({
                ...draft,
                calibration: {
                  ...draft.calibration,
                  perpendicular_camera: e.target.checked,
                  floor_distance_mm: e.target.checked ? draft.calibration.floor_distance_mm : null,
                },
              })
            }
          >
            Camera is perpendicular to floor
          </Checkbox>
          <label className="setting-field">
            <span>Floor distance from camera (mm)</span>
            <InputNumber
              aria-label="Floor distance"
              value={draft.calibration.floor_distance_mm}
              disabled={busy || !draft.calibration.perpendicular_camera}
              min={1}
              onChange={(v) =>
                change({
                  ...draft,
                  calibration: { ...draft.calibration, floor_distance_mm: v, floor_plane: null, id: null },
                })
              }
            />
          </label>
          <div className="settings-grid">
            {number('calibration', 'pallet_height_mm', 'Pallet support height (mm)', 0)}
            {number('alignment', 'target_angle_deg', 'Target angle (°)', -180, 180, 1)}
            {number('alignment', 'position_tolerance_px', 'Alignment tolerance (px)', 1)}
            {number('alignment', 'position_tolerance_mm', 'Alignment tolerance (mm)', 1)}
            {number('alignment', 'rotation_tolerance_deg', 'Rotation tolerance (°)', 0.1, 90, 0.5)}
            {number('alignment', 'height_band_mm', 'Pallet height band (mm)', 1)}
          </div>
          <h4>Target ROI · normalized coordinates</h4>
          <div className="roi-coordinates">
            {draft.roi.points.map(([x, y], i) => (
              <div key={i}>
                <span>P{i + 1}</span>
                <InputNumber
                  aria-label={`ROI point ${i + 1} X`}
                  min={0}
                  max={1}
                  step={0.01}
                  value={x}
                  disabled={busy}
                  onChange={(v) => {
                    if (v === null) return;
                    const points = [...draft.roi.points];
                    points[i] = [v, y];
                    change({ ...draft, roi: { points } });
                  }}
                />
                <InputNumber
                  aria-label={`ROI point ${i + 1} Y`}
                  min={0}
                  max={1}
                  step={0.01}
                  value={y}
                  disabled={busy}
                  onChange={(v) => {
                    if (v === null) return;
                    const points = [...draft.roi.points];
                    points[i] = [x, v];
                    change({ ...draft, roi: { points } });
                  }}
                />
              </div>
            ))}
          </div>
        </div>
      ),
    },
    {
      key: 'matching',
      label: 'Transfer QC',
      children: (
        <div className="settings-stack">
          <p className="settings-help">
            2D tolerance uses a pallet-local frame normalized to the configured canonical pallet width. RGB-D
            uses millimeters and requires valid floor calibration.
          </p>
          <div className="settings-grid">
            {number('matching', 'position_tolerance_px', 'Position tolerance (canonical px)', 1)}
            {number('matching', 'position_tolerance_mm', 'Position tolerance (mm)', 1)}
            {number('matching', 'size_tolerance_percent', 'Size tolerance (%)', 0.1, 100, 1)}
            {number('matching', 'canonical_pallet_width_px', 'Canonical pallet width (px)', 1)}
            {number('matching', 'position_weight', 'Position cost weight', 0.01, 10, 0.1)}
            {number('matching', 'size_weight', 'Size cost weight', 0, 10, 0.1)}
            {number('matching', 'orientation_weight', 'Orientation cost weight', 0, 10, 0.1)}
            {number('runtime', 'continuous_interval_seconds', 'Continuous interval (s)', 0.2, 3600, 0.2)}
          </div>
          <Checkbox
            checked={draft.matching.check_orientation}
            disabled={busy}
            onChange={(e) =>
              change({ ...draft, matching: { ...draft.matching, check_orientation: e.target.checked } })
            }
          >
            Require standing / lying orientation match
          </Checkbox>
        </div>
      ),
    },
    {
      key: 'advanced',
      label: 'Advanced JSON',
      children: (
        <div className="settings-stack">
          <p className="settings-help">
            Every threshold is exposed here. Use this for histogram templates, camera profiles and polygon
            coordinates. JSON is validated by the backend.
          </p>
          <Input.TextArea
            aria-label="Advanced configuration JSON"
            className="json-editor"
            rows={18}
            value={advanced}
            disabled={busy}
            onChange={(e) => setAdvanced(e.target.value)}
          />
          {jsonError && <Alert type="error" message={jsonError} />}
          <Button
            disabled={busy}
            onClick={() => {
              try {
                const value = JSON.parse(advanced) as Config;
                setJsonError('');
                void onSave(value);
              } catch {
                setJsonError('Enter valid JSON.');
              }
            }}
          >
            Validate & apply JSON
          </Button>
        </div>
      ),
    },
  ];
  return (
    <Modal
      open
      width={820}
      title={
        <div className="settings-title">
          Calibration & settings <span>REV {String(config.revision).padStart(3, '0')}</span>
        </div>
      }
      onCancel={close}
      footer={
        <div className="settings-footer">
          <span>
            <i className={`status-dot ${busy ? '' : 'on'}`} />
            {busy ? 'Applying settings & reprocessing…' : 'Controls auto-save after a short pause'}
          </span>
          <Button onClick={close}>Close</Button>
        </div>
      }
    >
      <Tabs items={tabs} />
    </Modal>
  );
}
