import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Input, InputNumber, Modal, Select, Space, Tag } from 'antd';
import { api, awaitJob, post } from '../api/client';
import type { Calibration, Config, Frame, JobTicket, Point, Recipe, RecipePage, ROI } from '../api/types';

type Layer = 'target' | 'search' | 'material' | 'roll' | 'floor';
const colors: Record<Layer, string> = {
  target: '#ffcd4a',
  search: '#49c2ff',
  material: '#57e5ac',
  roll: '#ff89bc',
  floor: '#c7b4ff',
};
const labels: Record<Layer, string> = {
  target: '01 · Pallet corners',
  search: '02 · Search region',
  material: '03 · Material patch',
  roll: '04 · Roll region',
  floor: '05 · Floor sample',
};

export default function TeachModal({
  frame,
  config,
  onClose,
  onApply,
}: {
  frame: Frame | null;
  config: Config;
  onClose: () => void;
  onApply: (config: Config) => Promise<boolean>;
}) {
  const compatible =
    frame && config.teaching?.image_width === frame.width && config.teaching?.image_height === frame.height;
  const [draft, setDraft] = useState(() => structuredClone(config));
  const [regions, setRegions] = useState<Record<Layer, Point[]>>(() => ({
    target: compatible ? config.teaching!.target.points : [],
    search: config.roi.points,
    material: compatible ? (config.teaching?.material_roi?.points ?? []) : [],
    roll: compatible ? (config.teaching?.roll_roi?.points ?? []) : [],
    floor: [],
  }));
  const [layer, setLayer] = useState<Layer>('target');
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [recipes, setRecipes] = useState<RecipePage>({ items: [], next_cursor: null });
  const [selected, setSelected] = useState<string>();
  const [confirmed, setConfirmed] = useState(config.teaching?.require_origin_confirmation ?? true);
  const [sizeTolerance, setSizeTolerance] = useState(config.teaching?.size_tolerance_percent ?? 20);
  const [preview, setPreview] = useState<{ signature: string; polygon: Point[] } | null>(null);
  const signature = JSON.stringify([regions, draft.alignment, draft.calibration]);
  const gesture = useRef<{ start: Point; corner?: number } | null>(null);
  const w = frame?.width ?? 640,
    h = frame?.height ?? 480;
  useEffect(() => {
    let active = true;
    api<RecipePage>('/recipes')
      .then((v) => {
        if (active) setRecipes(v);
      })
      .catch((e) => {
        if (active) setError(String(e));
      });
    return () => {
      active = false;
    };
  }, []);
  async function work(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  const coordinates = (event: React.PointerEvent<SVGSVGElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)),
      Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)),
    ];
  };
  const polygon = (points: Point[]) => points.map(([x, y]) => `${x * (w - 1)},${y * (h - 1)}`).join(' ');
  const setRegion = (key: Layer, points: Point[]) => setRegions((r) => ({ ...r, [key]: points }));
  function changeTolerance(
    key: 'position_tolerance_px' | 'position_tolerance_mm' | 'rotation_tolerance_deg',
    value: number | null,
  ) {
    if (value !== null) setDraft((d) => ({ ...d, alignment: { ...d.alignment, [key]: value } }));
  }
  async function prepare() {
    if (!frame || regions.target.length !== 4) throw new Error('Teach four corners on a real pinned frame.');
    const next: Config = {
      ...draft,
      roi: { points: regions.search },
      teaching: {
        source_frame_id: frame.id,
        image_width: w,
        image_height: h,
        camera_serial: null,
        intrinsics: null,
        target: { points: regions.target },
        material_roi: regions.material.length ? { points: regions.material } : null,
        roll_roi: regions.roll.length ? { points: regions.roll } : null,
        require_origin_confirmation: confirmed,
        size_tolerance_percent: sizeTolerance,
      },
    };
    return post<{ config: Config; acceptance_polygon: Point[] | null; position_unit: string }>('/teachings', {
      frame_id: frame.id,
      config: next,
    });
  }
  async function save() {
    if (!name.trim()) throw new Error('Name the recipe first.');
    const prepared = await prepare();
    const recipe = await post<Recipe>('/recipes', { name: name.trim(), config: prepared.config });
    setRecipes((r) => ({ ...r, items: [recipe, ...r.items] }));
    setSelected(recipe.id);
    if (await onApply(prepared.config)) onClose();
    else
      setError(
        'Recipe saved, but activation failed. Check the workstation error and load this saved recipe after resolving it.',
      );
  }
  const target = regions.target;
  const center =
    target.length === 4
      ? target.reduce((v, p) => [v[0] + (p[0] * (w - 1)) / 4, v[1] + (p[1] * (h - 1)) / 4] as Point, [
          0, 0,
        ] as Point)
      : null;
  const angle =
    target.length === 4
      ? (Math.atan2((target[1][1] - target[0][1]) * (h - 1), (target[1][0] - target[0][0]) * (w - 1)) * 180) /
        Math.PI
      : 0;
  const tolerance = draft.alignment.position_tolerance_px;
  return (
    <Modal
      open
      width={1180}
      title="Teach setup · pallet datum & inspection regions"
      onCancel={() => !busy && onClose()}
      maskClosable={false}
      closable={!busy}
      footer={
        <Space>
          <Button disabled={busy} onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="primary"
            loading={busy}
            disabled={!frame || target.length !== 4 || !name.trim()}
            onClick={() => void work(save)}
          >
            Save recipe & activate
          </Button>
        </Space>
      }
    >
      <div className="teach-library">
        <strong>Recipe library</strong>
        <Select
          aria-label="Saved recipe"
          placeholder="Select a saved setup"
          value={selected}
          onChange={setSelected}
          disabled={busy}
          style={{ minWidth: 270 }}
          options={recipes.items.map((r) => ({
            value: r.id,
            label: `${r.name} · ${new Date(r.created_at).toLocaleDateString()}`,
          }))}
        />
        <Button
          disabled={!selected || busy}
          onClick={() =>
            void work(async () => {
              const recipe = await api<Recipe>(`/recipes/${selected}`);
              if (await onApply(recipe.config)) onClose();
              else setError('Recipe activation failed. Check the workstation error.');
            })
          }
        >
          Load & activate
        </Button>
        {recipes.next_cursor && (
          <Button
            disabled={busy}
            onClick={() =>
              void work(async () => {
                const page = await api<RecipePage>(`/recipes?cursor=${recipes.next_cursor}`);
                setRecipes((r) => ({ items: [...r.items, ...page.items], next_cursor: page.next_cursor }));
              })
            }
          >
            More recipes
          </Button>
        )}
      </div>
      {error && <Alert type="error" showIcon message={error} />}
      {notice && <Alert type="success" showIcon message={notice} />}
      {!frame ? (
        <Alert
          type="info"
          showIcon
          message="Upload an actual image or connect a camera to teach a new setup. Saved recipes can still be activated."
        />
      ) : (
        <div className="teach-layout">
          <div>
            <div className="teach-tools">
              {(Object.keys(labels) as Layer[]).map((key) => (
                <Button
                  key={key}
                  disabled={busy || (key === 'floor' && !frame.capabilities.depth)}
                  type={key === layer ? 'primary' : 'default'}
                  onClick={() => setLayer(key)}
                >
                  {labels[key]}
                </Button>
              ))}
            </div>
            <p className="teach-instruction">
              {layer === 'target'
                ? 'Click four corners clockwise: O → +X → opposite → +Y. Drag a corner to adjust it.'
                : 'Drag a rectangle. Material and roll regions must lie inside the taught pallet; the floor sample must contain exposed floor only.'}
            </p>
            <div className="teach-canvas" style={{ aspectRatio: `${w}/${h}` }}>
              <img
                src={frame.image_urls?.rgb}
                alt="Pinned real frame for teaching pallet geometry"
                draggable={false}
              />
              <svg
                viewBox={`0 0 ${w} ${h}`}
                aria-label="Teach pallet corners and regions"
                onPointerDown={(e) => {
                  if (busy) return;
                  const p = coordinates(e);
                  e.currentTarget.setPointerCapture(e.pointerId);
                  if (layer === 'target') {
                    const corner = target.findIndex(
                      (t) => Math.hypot((t[0] - p[0]) * w, (t[1] - p[1]) * h) < Math.max(w, h) * 0.025,
                    );
                    if (corner >= 0) gesture.current = { start: p, corner };
                    else if (target.length < 4) setRegion('target', [...target, p]);
                  } else gesture.current = { start: p };
                }}
                onPointerMove={(e) => {
                  if (!gesture.current || busy) return;
                  const p = coordinates(e),
                    g = gesture.current;
                  if (g.corner !== undefined)
                    setRegion(
                      'target',
                      target.map((t, i) => (i === g.corner ? p : t)),
                    );
                  else {
                    const x = Math.min(g.start[0], p[0]),
                      y = Math.min(g.start[1], p[1]),
                      right = Math.max(g.start[0], p[0]),
                      bottom = Math.max(g.start[1], p[1]);
                    setRegion(layer, [
                      [x, y],
                      [right, y],
                      [right, bottom],
                      [x, bottom],
                    ]);
                  }
                }}
                onPointerUp={() => {
                  gesture.current = null;
                }}
                onPointerCancel={() => {
                  gesture.current = null;
                }}
              >
                {preview?.signature === signature && (
                  <polygon
                    points={preview.polygon.map((p) => p.join(',')).join(' ')}
                    fill="#ffcd4a"
                    fillOpacity={0.2}
                    stroke="#ffcd4a"
                    strokeWidth={2}
                    strokeDasharray="4 3"
                  />
                )}
                {(Object.keys(regions) as Layer[]).map((key) => (
                  <polygon
                    key={key}
                    points={polygon(regions[key])}
                    fill={colors[key]}
                    fillOpacity={key === layer ? 0.13 : 0.03}
                    stroke={colors[key]}
                    strokeWidth={key === layer ? 3 : 1.5}
                    strokeDasharray={key === 'search' ? '8 6' : undefined}
                  />
                ))}
                {target.map(([x, y], i) => (
                  <g key={i}>
                    <circle
                      cx={x * (w - 1)}
                      cy={y * (h - 1)}
                      r={Math.max(w, h) * 0.009}
                      fill={colors.target}
                    />
                    <text
                      x={x * (w - 1) + 9}
                      y={y * (h - 1) - 9}
                      fill="white"
                      stroke="#17232c"
                      paintOrder="stroke"
                      strokeWidth={3}
                      fontSize={Math.max(w, h) * 0.022}
                    >
                      {['O', '+X', '2', '+Y'][i]}
                    </text>
                  </g>
                ))}
                {center && !frame.capabilities.depth && (
                  <g
                    transform={`translate(${center.join(' ')}) rotate(${angle})`}
                    stroke={colors.target}
                    fill="none"
                  >
                    <rect
                      x={-tolerance}
                      y={-tolerance}
                      width={2 * tolerance}
                      height={2 * tolerance}
                      strokeDasharray="4 3"
                    />
                    <path d={`M 0 0 L ${w * 0.12} 0 M 0 0 L 0 ${h * 0.12}`} />
                    {[-1, 1].map((sign) => (
                      <path
                        key={sign}
                        transform={`rotate(${sign * draft.alignment.rotation_tolerance_deg})`}
                        d={`M 0 0 L ${w * 0.12} 0`}
                        strokeDasharray="3 3"
                      />
                    ))}
                  </g>
                )}
              </svg>
            </div>
            <div className="teach-legend">
              {(Object.keys(labels) as Layer[]).map((key) => (
                <span key={key}>
                  <i style={{ background: colors[key] }} />
                  {labels[key].slice(5)}
                </span>
              ))}
            </div>
            <Space wrap>
              <Button disabled={busy} onClick={() => setRegion(layer, [])}>
                Clear selected region
              </Button>
              <Button
                disabled={busy || !target.length}
                onClick={() => setRegion('target', target.slice(0, -1))}
              >
                Undo corner
              </Button>
              <Button
                disabled={busy || target.length !== 4}
                onClick={() => setRegion('target', [...target.slice(1), target[0]])}
              >
                Cycle origin
              </Button>
            </Space>
            <details className="teach-coordinates">
              <summary>Precise corner coordinates (pixels)</summary>
              {target.map((p, i) => (
                <div key={i}>
                  <strong>{['O', '+X', '2', '+Y'][i]}</strong>
                  {([0, 1] as const).map((axis) => (
                    <InputNumber
                      key={axis}
                      aria-label={`Corner ${i} ${axis ? 'Y' : 'X'}`}
                      disabled={busy}
                      min={0}
                      max={(axis ? h : w) - 1}
                      value={Math.round(p[axis] * ((axis ? h : w) - 1))}
                      onChange={(v) => {
                        if (v !== null)
                          setRegion(
                            'target',
                            target.map((t, j) =>
                              j === i
                                ? (t.map((n, k) => (k === axis ? v / ((axis ? h : w) - 1) : n)) as Point)
                                : t,
                            ),
                          );
                      }}
                    />
                  ))}
                </div>
              ))}
            </details>
          </div>
          <aside className="teach-settings">
            <Tag color="blue">
              PINNED · {w} × {h}
            </Tag>
            <label>
              Recipe name
              <Input
                value={name}
                maxLength={120}
                disabled={busy}
                onChange={(e) => setName(e.target.value)}
                placeholder="Line 01 · wood pallet"
              />
            </label>
            <label>
              Position tolerance · pixels
              <InputNumber
                min={0.1}
                value={draft.alignment.position_tolerance_px}
                disabled={busy}
                onChange={(v) => changeTolerance('position_tolerance_px', v)}
              />
            </label>
            <label>
              Position tolerance · mm (RGB-D)
              <InputNumber
                min={0.1}
                value={draft.alignment.position_tolerance_mm}
                disabled={busy}
                onChange={(v) => changeTolerance('position_tolerance_mm', v)}
              />
            </label>
            <label>
              Rotation tolerance · degrees
              <InputNumber
                min={0.1}
                max={90}
                value={draft.alignment.rotation_tolerance_deg}
                disabled={busy}
                onChange={(v) => changeTolerance('rotation_tolerance_deg', v)}
              />
            </label>
            <label>
              Pallet size tolerance · %
              <InputNumber
                min={0.1}
                max={100}
                value={sizeTolerance}
                disabled={busy}
                onChange={(v) => v !== null && setSizeTolerance(v)}
              />
            </label>
            <p className="teach-instruction">
              {frame.capabilities.depth
                ? 'Fit the floor, then preview the mm acceptance region projected onto this image. Preview hides after geometry or tolerance changes.'
                : 'Dashed center box = accepted center position. Dashed rays = angle limits. Dimensions are checked separately.'}
            </p>
            <Button
              disabled={busy || target.length !== 4}
              onClick={() =>
                void work(async () => {
                  const result = await prepare();
                  if (!result.acceptance_polygon)
                    throw new Error(
                      'Metric preview needs a valid floor calibration and supported projection model.',
                    );
                  setPreview({ signature, polygon: result.acceptance_polygon });
                  setNotice(`Accepted center region · ${result.position_unit}. Setup geometry validated.`);
                })
              }
            >
              Validate & preview tolerances
            </Button>
            <Checkbox checked={confirmed} disabled={busy} onChange={(e) => setConfirmed(e.target.checked)}>
              Require physical origin confirmation on every inspection
            </Checkbox>
            {!confirmed && (
              <Alert
                type="warning"
                message="Axis-only mode cannot detect a 180° reversal. Use only when pallet direction is mechanically constrained."
              />
            )}
            <h4>Material teaching</h4>
            <p className="teach-instruction">
              Draw an exposed, clean material patch. Sampling updates the color profile, not the segmentation
              model.
            </p>
            <Space>
              {(['wood', 'plastic'] as const).map((material) => (
                <Button
                  key={material}
                  disabled={busy || !regions.material.length}
                  onClick={() =>
                    void work(async () => {
                      const sample = await post<{ histogram: number[]; sample_pixels: number }>(
                        '/material-samples',
                        {
                          frame_id: frame.id,
                          roi: { points: regions.material },
                          bins: draft.classifier.histogram_bins,
                        },
                      );
                      setDraft((d) => ({
                        ...d,
                        classifier: { ...d.classifier, [`${material}_histogram`]: sample.histogram },
                      }));
                      setNotice(`${material} profile sampled from ${sample.sample_pixels} real pixels.`);
                    })
                  }
                >
                  Learn {material}
                </Button>
              ))}
            </Space>
            <h4>Floor calibration</h4>
            <Button
              disabled={busy || !frame.capabilities.depth || !regions.floor.length}
              onClick={() =>
                void work(async () => {
                  const fitted = await awaitJob<Calibration>(
                    await post<JobTicket>('/calibrations', {
                      frame_id: frame.id,
                      roi: { points: regions.floor } as ROI,
                    }),
                  );
                  setDraft((d) => ({
                    ...d,
                    calibration: {
                      ...d.calibration,
                      id: fitted.id,
                      floor_plane: fitted.plane,
                      intrinsics: fitted.intrinsics,
                      camera_serial: fitted.camera_serial,
                      floor_distance_mm: null,
                    },
                  }));
                  setNotice(
                    `Floor fitted · residual ${fitted.rms_mm.toFixed(2)} mm. Set pallet height before saving.`,
                  );
                })
              }
            >
              Fit exposed floor
            </Button>
            <label>
              Pallet support height · mm
              <InputNumber
                min={0}
                value={draft.calibration.pallet_height_mm}
                disabled={busy}
                onChange={(v) =>
                  v !== null &&
                  setDraft((d) => ({ ...d, calibration: { ...d.calibration, pallet_height_mm: v } }))
                }
              />
            </label>
            <p className="teach-instruction">
              Changing taught geometry invalidates the transfer reference. Capture a new reference after
              confirming its origin. A moved camera must be re-taught.
            </p>
          </aside>
        </div>
      )}
    </Modal>
  );
}
