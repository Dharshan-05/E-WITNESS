import React, { useState } from 'react';
import { X, Download, Copy, Check, FileSpreadsheet, FileCode, ShieldAlert } from 'lucide-react';
import { Button } from '../ui/Button';
import type { AuditEventExportResponse } from '../../types/audit';

export interface AuditExportModalProps {
  isOpen: boolean;
  isExporting: boolean;
  exportResult: AuditEventExportResponse | null;
  onClose: () => void;
  onExecuteExport: (format: 'json' | 'csv', limit: number) => Promise<void>;
}

export const AuditExportModal: React.FC<AuditExportModalProps> = ({
  isOpen,
  isExporting,
  exportResult,
  onClose,
  onExecuteExport,
}) => {
  const [format, setFormat] = useState<'json' | 'csv'>('json');
  const [limit, setLimit] = useState<number>(500);
  const [copied, setCopied] = useState<boolean>(false);

  if (!isOpen) return null;

  const handleExport = async (e: React.FormEvent) => {
    e.preventDefault();
    await onExecuteExport(format, limit);
  };

  const handleDownload = () => {
    if (!exportResult) return;
    const blob = new Blob([exportResult.content], {
      type: format === 'json' ? 'application/json' : 'text/csv;charset=utf-8;',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute(
      'download',
      `audit_ledger_export_${new Date().toISOString().substring(0, 10)}.${format}`
    );
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleCopyContent = () => {
    if (!exportResult) return;
    navigator.clipboard.writeText(exportResult.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm animate-in fade-in duration-150">
      <div
        className="w-full max-w-xl rounded-xl bg-white shadow-2xl border border-slate-200 overflow-hidden flex flex-col"
        role="dialog"
        aria-modal="true"
        aria-labelledby="audit-export-title"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-slate-50">
          <div className="flex items-center gap-2.5">
            <Download className="h-5 w-5 text-indigo-600" />
            <h2 id="audit-export-title" className="text-base font-bold text-slate-900">
              Export Audit Ledger Records
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-5 text-xs">
          <div className="p-3.5 rounded-lg bg-amber-50/70 border border-amber-200 text-amber-900 flex items-start gap-2.5">
            <ShieldAlert className="h-4 w-4 text-amber-700 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <span className="font-semibold block">Export Governance & Formula Injection Defense</span>
              <p className="text-[11px] text-amber-800 leading-relaxed">
                Exports are strictly bounded by your department authorization and recorded into the tamper-evident
                audit chain. CSV cells beginning with formula triggers (<code className="font-mono bg-amber-100 px-1 rounded">= + - @</code>)
                are sanitized with leading apostrophes to protect spreadsheet analysts.
              </p>
            </div>
          </div>

          {!exportResult ? (
            <form onSubmit={handleExport} className="space-y-4">
              <div className="space-y-2">
                <span className="block font-medium text-slate-700">Export Format</span>
                <div className="grid grid-cols-2 gap-3">
                  <label
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      format === 'json'
                        ? 'border-indigo-600 bg-indigo-50/40 text-indigo-900'
                        : 'border-slate-200 hover:bg-slate-50 text-slate-700'
                    }`}
                  >
                    <input
                      type="radio"
                      name="export_format"
                      value="json"
                      checked={format === 'json'}
                      onChange={() => setFormat('json')}
                      className="sr-only"
                    />
                    <FileCode className="h-4 w-4 text-indigo-600" />
                    <div>
                      <span className="font-semibold block">JSON Array</span>
                      <span className="text-[11px] text-slate-500">Structured raw machine-readable records</span>
                    </div>
                  </label>

                  <label
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      format === 'csv'
                        ? 'border-indigo-600 bg-indigo-50/40 text-indigo-900'
                        : 'border-slate-200 hover:bg-slate-50 text-slate-700'
                    }`}
                  >
                    <input
                      type="radio"
                      name="export_format"
                      value="csv"
                      checked={format === 'csv'}
                      onChange={() => setFormat('csv')}
                      className="sr-only"
                    />
                    <FileSpreadsheet className="h-4 w-4 text-emerald-600" />
                    <div>
                      <span className="font-semibold block">CSV Spreadsheet</span>
                      <span className="text-[11px] text-slate-500">Sanitized tabular ledger rows</span>
                    </div>
                  </label>
                </div>
              </div>

              <div>
                <label htmlFor="export-limit" className="block font-medium text-slate-700 mb-1">
                  Maximum Records Bound (Max 1,000)
                </label>
                <input
                  id="export-limit"
                  type="number"
                  min="1"
                  max="1000"
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-xs focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div className="pt-2 flex justify-end gap-2">
                <Button type="button" variant="outline" size="sm" onClick={onClose}>
                  Cancel
                </Button>
                <Button type="submit" size="sm" isLoading={isExporting} className="bg-indigo-600 text-white">
                  Generate Export Payload
                </Button>
              </div>
            </form>
          ) : (
            <div className="space-y-4">
              <div className="p-4 rounded-lg bg-slate-50 border border-slate-200 space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-500">Total Exported Records:</span>
                  <span className="font-bold text-slate-900">{exportResult.total_records}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-500">Format:</span>
                  <span className="font-semibold uppercase text-slate-800">{exportResult.export_format}</span>
                </div>
                <div>
                  <span className="text-slate-500 block mb-1">SHA-256 Digest:</span>
                  <div className="p-2 rounded bg-white border border-slate-200 font-mono text-[11px] break-all text-slate-700">
                    {exportResult.hash_digest}
                  </div>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleCopyContent}
                  className="flex items-center gap-1.5"
                >
                  {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
                  <span>{copied ? 'Copied Content' : 'Copy Content'}</span>
                </Button>
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={handleDownload}
                  className="flex items-center gap-1.5 bg-indigo-600 text-white"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span>Download File</span>
                </Button>
                <Button type="button" variant="ghost" size="sm" onClick={onClose}>
                  Done
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
