import { useState } from 'react';
import { Alert, Button, Modal, Segmented } from 'antd';
import { FileImage, UploadCloud } from 'lucide-react';

export default function UploadModal({
  role,
  busy,
  onClose,
  onSubmit,
}: {
  role: string;
  busy: boolean;
  onClose: () => void;
  onSubmit: (data: FormData, name: string) => void;
}) {
  const [kind, setKind] = useState('RGB image');
  const [files, setFiles] = useState<Record<string, File>>({});
  const ready =
    kind === 'Recording'
      ? !!files.bag
      : !!files.rgb && (kind !== 'RGB + Depth' || (!!files.depth && !!files.metadata));
  const picker = (key: string, label: string, accept: string) => (
    <label
      className="file-picker"
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        const file = e.dataTransfer.files[0];
        if (file) setFiles((f) => ({ ...f, [key]: file }));
      }}
    >
      <FileImage size={22} />
      <span>
        <strong>{files[key]?.name ?? label}</strong>
        <small>
          {files[key]
            ? `${(files[key].size / 1024 / 1024).toFixed(2)} MB · Click to replace`
            : `Choose or drop a file · ${accept}`}
        </small>
      </span>
      <input
        aria-label={label}
        type="file"
        accept={accept}
        disabled={busy}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) setFiles((f) => ({ ...f, [key]: file }));
        }}
      />
    </label>
  );
  return (
    <Modal
      open
      title={`Load ${role.toLowerCase()}`}
      onCancel={onClose}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="primary"
            loading={busy}
            disabled={!ready}
            icon={<UploadCloud size={16} />}
            onClick={() => {
              const data = new FormData();
              for (const key of kind === 'Recording'
                ? ['bag']
                : kind === 'RGB + Depth'
                  ? ['rgb', 'depth', 'metadata']
                  : ['rgb'])
                data.append(key, files[key]);
              onSubmit(data, (files.rgb ?? files.bag).name);
            }}
          >
            Load & inspect
          </Button>
        </>
      }
      destroyOnHidden
    >
      <div className="upload-content">
        <Segmented
          block
          value={kind}
          onChange={(v) => setKind(v)}
          options={['RGB image', 'RGB + Depth', 'Recording']}
        />
        {kind === 'Recording' ? (
          picker('bag', 'RealSense recording', '.bag')
        ) : (
          <>
            {picker('rgb', 'RGB image', '.jpg,.jpeg,.png')}
            {kind === 'RGB + Depth' && (
              <>
                {picker('depth', 'Aligned depth map', '.png,.npy')}
                {picker('metadata', 'Camera metadata', '.json')}
              </>
            )}
          </>
        )}
        <Alert
          type="info"
          showIcon
          message={
            kind === 'RGB image' ? '2D inspection · pixel measurements' : 'Calibrated RGB-D inspection'
          }
          description={
            kind === 'RGB image'
              ? 'Material, alignment, segmentation and pallet-local layout. No fabricated depth or millimeter values.'
              : kind === 'Recording'
                ? 'Requires the RealSense SDK. Playback starts paused so you can inspect a specific frame.'
                : 'Use a 16-bit PNG or numeric NPY with aligned_to_color, depth_scale_m and camera intrinsics in the JSON sidecar.'
          }
        />
      </div>
    </Modal>
  );
}
