import React, { useState } from 'react';
import { X, Download, FileSpreadsheet, FileText, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';
import { exportReport } from '../../api/analytics';
import type { ReportFormat, ReportType } from '../../types/analytics';
import { Button } from '../ui/Button';

export interface ReportExportModalProps {
  isOpen: boolean;
  onClose: () => void;
  startDate?: string | null;
  endDate?: string | null;
  departmentId?: string | null;
}

export const ReportExportModal: React.FC<ReportExportModalProps> = ({
  isOpen,
  onClose,
  startDate,
  endDate,
  departmentId,
}) => {
  const [reportType, setReportType] = useState<ReportType>('operational_summary');
  const [exportFormat, setExportFormat] = useState<ReportFormat>('csv');
  const [isExporting, setIsExporting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleExport = async () => {
    setIsExporting(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    try {
      const { blob, filename } = await exportReport({
        report_type: reportType,
        export_format: exportFormat,
        start_date: startDate,
        end_date: endDate,
        department_id: departmentId,
      });

      // Trigger browser download via object URL
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      setSuccessMessage(`Successfully downloaded ${filename}`);
      setTimeout(() => {
        onClose();
        setSuccessMessage(null);
      }, 1500);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Report export failed.');
    } finally {
      setIsExporting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="export-modal-title"
    >
      <div className="w-full max-w-md rounded-xl border border-slate-200 bg-white p-6 shadow-xl">
        <div className="flex items-center justify-between pb-3 border-b border-slate-100 mb-4">
          <div className="flex items-center gap-2">
            <Download className="h-5 w-5 text-indigo-600" aria-hidden="true" />
            <h3 id="export-modal-title" className="text-base font-bold text-slate-900">
              Export Operational Report
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close export dialog"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <p className="text-xs text-slate-600 mb-4">
          Generate an institutional audit report with macro-sanitized CSV or authenticated PDF output.
          Exports are restricted to your department scope and observation dates.
        </p>

        <div className="space-y-4 text-xs">
          {/* Report Type Selector */}
          <div>
            <label className="block font-semibold text-slate-700 mb-1.5">Report Domain</label>
            <div className="grid grid-cols-2 gap-2">
              {[
                { type: 'operational_summary', label: 'Operational Overview' },
                { type: 'incidents', label: 'Incidents Registry' },
                { type: 'cases', label: 'Investigation Cases' },
                { type: 'human_reviews', label: 'AI Human Oversight' },
              ].map((item) => (
                <button
                  key={item.type}
                  type="button"
                  onClick={() => setReportType(item.type as ReportType)}
                  className={`flex flex-col text-left p-2.5 rounded-lg border transition-all ${
                    reportType === item.type
                      ? 'border-indigo-600 bg-indigo-50/50 text-indigo-950 font-semibold'
                      : 'border-slate-200 hover:bg-slate-50 text-slate-700'
                  }`}
                >
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Format Selector */}
          <div>
            <label className="block font-semibold text-slate-700 mb-1.5">Document Format</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setExportFormat('csv')}
                className={`flex items-center gap-2 p-2.5 rounded-lg border transition-all ${
                  exportFormat === 'csv'
                    ? 'border-indigo-600 bg-indigo-50/50 text-indigo-950 font-semibold'
                    : 'border-slate-200 hover:bg-slate-50 text-slate-700'
                }`}
              >
                <FileSpreadsheet className="h-4 w-4 text-emerald-600" aria-hidden="true" />
                <span>Sanitized CSV</span>
              </button>

              <button
                type="button"
                onClick={() => setExportFormat('pdf')}
                className={`flex items-center gap-2 p-2.5 rounded-lg border transition-all ${
                  exportFormat === 'pdf'
                    ? 'border-indigo-600 bg-indigo-50/50 text-indigo-950 font-semibold'
                    : 'border-slate-200 hover:bg-slate-50 text-slate-700'
                }`}
              >
                <FileText className="h-4 w-4 text-rose-600" aria-hidden="true" />
                <span>Official PDF</span>
              </button>
            </div>
          </div>

          {/* Feedback banners */}
          {errorMessage && (
            <div className="flex items-center gap-2 rounded-lg border border-rose-200 bg-rose-50 p-2.5 text-rose-700">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{errorMessage}</span>
            </div>
          )}

          {successMessage && (
            <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 p-2.5 text-emerald-700">
              <CheckCircle2 className="h-4 w-4 shrink-0" />
              <span>{successMessage}</span>
            </div>
          )}
        </div>

        <div className="mt-6 flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
          <Button variant="outline" size="sm" onClick={onClose} disabled={isExporting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleExport}
            disabled={isExporting}
            leftIcon={isExporting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
          >
            {isExporting ? 'Generating Report...' : 'Download Export'}
          </Button>
        </div>
      </div>
    </div>
  );
};
