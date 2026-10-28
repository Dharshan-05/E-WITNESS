import React, { useState } from 'react';
import {
  GraduationCap,
  UserX,
  Building,
  AlertTriangle,
  ShieldAlert,
  FileText,
  CheckCircle2,
  ArrowRight,
  ArrowLeft,
  Copy,
  Check,
  Info,
  Lock,
  RotateCcw,
} from 'lucide-react';
import { Button } from '../ui/Button';
import { Badge } from '../ui/Badge';
import { Alert } from '../ui/Alert';
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '../ui/Card';
import {
  type IncidentCategory,
  type IncidentSeverity,
  type IncidentCreate,
  type IncidentRead,
  INCIDENT_CATEGORIES,
  INCIDENT_SEVERITIES,
} from '../../types/incident';
import { submitIncident } from '../../api/incident';
import { useAuth } from '../../auth';
import { ApiError } from '../../types/api';

interface IncidentIntakeWizardProps {
  onSuccess?: (incident: IncidentRead) => void;
  onViewMyReports?: () => void;
}

export const IncidentIntakeWizard: React.FC<IncidentIntakeWizardProps> = ({
  onSuccess,
  onViewMyReports,
}) => {
  const { user } = useAuth();

  // Wizard Step: 1 = Classification, 2 = Details, 3 = Review, 4 = Confirmation
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);

  // Form State
  const [category, setCategory] = useState<IncidentCategory | null>(null);
  const [severity, setSeverity] = useState<IncidentSeverity>('medium');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [location, setLocation] = useState('');
  const [occurredAt, setOccurredAt] = useState('');

  // Validation Errors
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Success State
  const [createdIncident, setCreatedIncident] = useState<IncidentRead | null>(null);
  const [copiedRef, setCopiedRef] = useState(false);

  // Category Icon Resolver
  const getCategoryIcon = (iconName: string) => {
    switch (iconName) {
      case 'GraduationCap':
        return <GraduationCap className="h-5 w-5 text-indigo-600" />;
      case 'UserX':
        return <UserX className="h-5 w-5 text-rose-600" />;
      case 'Building':
        return <Building className="h-5 w-5 text-amber-600" />;
      case 'AlertTriangle':
        return <AlertTriangle className="h-5 w-5 text-yellow-600" />;
      case 'ShieldAlert':
        return <ShieldAlert className="h-5 w-5 text-red-600" />;
      default:
        return <FileText className="h-5 w-5 text-slate-600" />;
    }
  };

  // Step 1 Validation
  const validateStep1 = (): boolean => {
    const newErrors: Record<string, string> = {};
    if (!category) {
      newErrors.category = 'Please select a primary incident classification category.';
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Step 2 Validation
  const validateStep2 = (): boolean => {
    const newErrors: Record<string, string> = {};

    const trimmedTitle = title.trim();
    if (!trimmedTitle) {
      newErrors.title = 'Incident title is required.';
    } else if (trimmedTitle.length < 5) {
      newErrors.title = 'Incident title must be at least 5 characters long.';
    } else if (trimmedTitle.length > 200) {
      newErrors.title = 'Incident title cannot exceed 200 characters.';
    }

    const trimmedDesc = description.trim();
    if (!trimmedDesc) {
      newErrors.description = 'Incident narrative description is required.';
    } else if (trimmedDesc.length < 10) {
      newErrors.description = 'Narrative description must be at least 10 characters long.';
    } else if (trimmedDesc.length > 10000) {
      newErrors.description = 'Narrative description cannot exceed 10,000 characters.';
    }

    const trimmedLoc = location.trim();
    if (!trimmedLoc) {
      newErrors.location = 'Physical occurrence location is required.';
    } else if (trimmedLoc.length < 2) {
      newErrors.location = 'Location must be at least 2 characters.';
    } else if (trimmedLoc.length > 255) {
      newErrors.location = 'Location cannot exceed 255 characters.';
    }

    if (!occurredAt) {
      newErrors.occurredAt = 'Date and time of occurrence is required.';
    } else {
      const occurrenceDate = new Date(occurredAt);
      if (isNaN(occurrenceDate.getTime())) {
        newErrors.occurredAt = 'Invalid occurrence date format.';
      } else if (occurrenceDate.getTime() > Date.now()) {
        newErrors.occurredAt = 'Incident occurrence timestamp cannot be in the future.';
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleNextFromStep1 = () => {
    if (validateStep1()) {
      setStep(2);
    }
  };

  const handleNextFromStep2 = () => {
    if (validateStep2()) {
      setStep(3);
    }
  };

  const handleBack = () => {
    setSubmitError(null);
    if (step === 2) setStep(1);
    if (step === 3) setStep(2);
  };

  const handleSubmit = async () => {
    setSubmitError(null);

    if (!category) {
      setStep(1);
      return;
    }

    if (!validateStep2()) {
      setStep(2);
      return;
    }

    setIsSubmitting(true);
    try {
      // Convert occurredAt to UTC ISO 8601 string
      const isoOccurredAt = new Date(occurredAt).toISOString();

      const payload: IncidentCreate = {
        title: title.trim(),
        description: description.trim(),
        category,
        severity,
        location: location.trim(),
        occurred_at: isoOccurredAt,
      };

      const result = await submitIncident(payload);
      setCreatedIncident(result);
      setStep(4);
      if (onSuccess) {
        onSuccess(result);
      }
    } catch (err: unknown) {
      if (err instanceof ApiError) {
        let msg = err.message;
        if (err.details && err.details.length > 0) {
          msg += ` (${err.details.map((d) => d.message).join('; ')})`;
        }
        setSubmitError(msg);
      } else if (err instanceof Error) {
        setSubmitError(err.message);
      } else {
        setSubmitError('Failed to submit incident report. Please verify connection and try again.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReset = () => {
    setCategory(null);
    setSeverity('medium');
    setTitle('');
    setDescription('');
    setLocation('');
    setOccurredAt('');
    setErrors({});
    setSubmitError(null);
    setCreatedIncident(null);
    setStep(1);
  };

  const handleCopyRef = async () => {
    if (createdIncident?.reference_number) {
      try {
        await navigator.clipboard.writeText(createdIncident.reference_number);
        setCopiedRef(true);
        setTimeout(() => setCopiedRef(false), 2000);
      } catch {
        // clipboard write may fail in insecure test contexts
      }
    }
  };

  const selectedCategoryObj = INCIDENT_CATEGORIES.find((c) => c.value === category);
  const selectedSeverityObj = INCIDENT_SEVERITIES.find((s) => s.value === severity);

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Wizard Progress Stepper */}
      <nav aria-label="Incident Intake Progress" className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
        <ol className="flex items-center justify-between text-xs sm:text-sm font-medium text-slate-500">
          <li className={`flex items-center space-x-2 ${step === 1 ? 'text-indigo-600 font-semibold' : step > 1 ? 'text-emerald-600' : ''}`}>
            <span
              className={`flex items-center justify-center w-7 h-7 rounded-full border text-xs font-bold ${
                step === 1
                  ? 'border-indigo-600 bg-indigo-50 text-indigo-600'
                  : step > 1
                  ? 'border-emerald-600 bg-emerald-50 text-emerald-600'
                  : 'border-slate-300 bg-slate-50 text-slate-500'
              }`}
            >
              1
            </span>
            <span className="hidden sm:inline">Classification</span>
          </li>
          <div className="flex-1 mx-3 h-0.5 bg-slate-200" />
          <li className={`flex items-center space-x-2 ${step === 2 ? 'text-indigo-600 font-semibold' : step > 2 ? 'text-emerald-600' : ''}`}>
            <span
              className={`flex items-center justify-center w-7 h-7 rounded-full border text-xs font-bold ${
                step === 2
                  ? 'border-indigo-600 bg-indigo-50 text-indigo-600'
                  : step > 2
                  ? 'border-emerald-600 bg-emerald-50 text-emerald-600'
                  : 'border-slate-300 bg-slate-50 text-slate-500'
              }`}
            >
              2
            </span>
            <span className="hidden sm:inline">Details</span>
          </li>
          <div className="flex-1 mx-3 h-0.5 bg-slate-200" />
          <li className={`flex items-center space-x-2 ${step === 3 ? 'text-indigo-600 font-semibold' : step > 3 ? 'text-emerald-600' : ''}`}>
            <span
              className={`flex items-center justify-center w-7 h-7 rounded-full border text-xs font-bold ${
                step === 3
                  ? 'border-indigo-600 bg-indigo-50 text-indigo-600'
                  : step > 3
                  ? 'border-emerald-600 bg-emerald-50 text-emerald-600'
                  : 'border-slate-300 bg-slate-50 text-slate-500'
              }`}
            >
              3
            </span>
            <span className="hidden sm:inline">Review & Submit</span>
          </li>
          <div className="flex-1 mx-3 h-0.5 bg-slate-200" />
          <li className={`flex items-center space-x-2 ${step === 4 ? 'text-emerald-600 font-semibold' : ''}`}>
            <span
              className={`flex items-center justify-center w-7 h-7 rounded-full border text-xs font-bold ${
                step === 4
                  ? 'border-emerald-600 bg-emerald-50 text-emerald-600'
                  : 'border-slate-300 bg-slate-50 text-slate-500'
              }`}
            >
              4
            </span>
            <span className="hidden sm:inline">Confirmation</span>
          </li>
        </ol>
      </nav>

      {/* STEP 1: CATEGORY & SEVERITY */}
      {step === 1 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Select Incident Category & Severity</CardTitle>
                <CardDescription>
                  Choose the category that best describes the incident and select the estimated urgency.
                </CardDescription>
              </div>
              <Badge variant="primary">Step 1 of 3</Badge>
            </div>
          </CardHeader>

          <CardContent className="space-y-6">
            {errors.category && (
              <Alert variant="error" title="Category Required">
                {errors.category}
              </Alert>
            )}

            {/* Category Grid */}
            <div>
              <label className="block text-sm font-semibold text-slate-800 mb-3">
                Classification Category <span className="text-rose-500">*</span>
              </label>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3" role="radiogroup" aria-label="Incident Category Selection">
                {INCIDENT_CATEGORIES.map((cat) => {
                  const isSelected = category === cat.value;
                  return (
                    <button
                      key={cat.value}
                      type="button"
                      role="radio"
                      aria-checked={isSelected}
                      onClick={() => {
                        setCategory(cat.value);
                        if (errors.category) {
                          setErrors((prev) => {
                            const next = { ...prev };
                            delete next.category;
                            return next;
                          });
                        }
                      }}
                      className={`text-left p-4 rounded-lg border transition-all flex items-start space-x-3 ${
                        isSelected
                          ? 'border-indigo-600 bg-indigo-50/50 ring-2 ring-indigo-500/20'
                          : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
                      }`}
                    >
                      <div className="p-2 rounded-md bg-white border border-slate-200 shrink-0">
                        {getCategoryIcon(cat.iconName)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-slate-900 text-sm">{cat.label}</div>
                        <div className="text-xs text-slate-500 mt-0.5 leading-relaxed">{cat.description}</div>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Severity Selector */}
            <div className="pt-4 border-t border-slate-100">
              <label className="block text-sm font-semibold text-slate-800 mb-1">
                Estimated Severity Level
              </label>
              <p className="text-xs text-slate-500 mb-3">
                Select the severity level based on immediate risk or disruption to the campus community.
              </p>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" role="radiogroup" aria-label="Incident Severity Selection">
                {INCIDENT_SEVERITIES.map((sev) => {
                  const isSelected = severity === sev.value;
                  return (
                    <button
                      key={sev.value}
                      type="button"
                      role="radio"
                      aria-checked={isSelected}
                      onClick={() => setSeverity(sev.value)}
                      className={`text-left p-3 rounded-lg border transition-all ${
                        isSelected
                          ? 'border-indigo-600 bg-indigo-50/40 ring-2 ring-indigo-500/20'
                          : 'border-slate-200 bg-white hover:border-slate-300'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-bold uppercase tracking-wider">{sev.label}</span>
                        <Badge variant={sev.badgeVariant} size="sm">
                          {sev.value}
                        </Badge>
                      </div>
                      <div className="text-xs text-slate-500 line-clamp-2">{sev.description}</div>
                    </button>
                  );
                })}
              </div>
            </div>
          </CardContent>

          <CardFooter className="flex justify-end space-x-3">
            <Button
              variant="primary"
              onClick={handleNextFromStep1}
              rightIcon={<ArrowRight className="h-4 w-4" />}
            >
              Continue to Details
            </Button>
          </CardFooter>
        </Card>
      )}

      {/* STEP 2: NARRATIVE & CONTEXT DETAILS */}
      {step === 2 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Incident Narrative & Context</CardTitle>
                <CardDescription>
                  Provide a clear summary title, factual description, physical location, and exact occurrence timestamp.
                </CardDescription>
              </div>
              <Badge variant="primary">Step 2 of 3</Badge>
            </div>
          </CardHeader>

          <CardContent className="space-y-5">
            {/* Guidance Alert */}
            <div className="p-3.5 bg-blue-50 border border-blue-200 rounded-lg flex items-start space-x-3 text-xs text-blue-900">
              <Info className="h-5 w-5 text-blue-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-semibold block mb-0.5">Factual Reporting Standards</span>
                Document observable factual details: specific dates, times, campus locations, and direct observations.
                Avoid speculation or unnecessary private personal identifiable data.
              </div>
            </div>

            {/* Title */}
            <div>
              <div className="flex justify-between items-center mb-1">
                <label htmlFor="incident-title" className="text-sm font-semibold text-slate-800">
                  Incident Title <span className="text-rose-500">*</span>
                </label>
                <span className={`text-xs ${title.length > 200 ? 'text-rose-500 font-semibold' : 'text-slate-400'}`}>
                  {title.length}/200
                </span>
              </div>
              <input
                id="incident-title"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g., Unauthorized access observed in Engineering Lab 204"
                aria-invalid={!!errors.title}
                aria-describedby={errors.title ? 'title-error' : undefined}
                className={`w-full px-3.5 py-2.5 text-sm rounded-lg border bg-white focus:outline-none focus:ring-2 ${
                  errors.title
                    ? 'border-rose-400 focus:ring-rose-200'
                    : 'border-slate-300 focus:border-indigo-600 focus:ring-indigo-100'
                }`}
              />
              {errors.title && (
                <p id="title-error" className="mt-1 text-xs text-rose-600" role="alert">
                  {errors.title}
                </p>
              )}
            </div>

            {/* Description */}
            <div>
              <div className="flex justify-between items-center mb-1">
                <label htmlFor="incident-description" className="text-sm font-semibold text-slate-800">
                  Factual Narrative Statement <span className="text-rose-500">*</span>
                </label>
                <span className={`text-xs ${description.length > 10000 ? 'text-rose-500 font-semibold' : 'text-slate-400'}`}>
                  {description.length}/10,000 (min 10)
                </span>
              </div>
              <textarea
                id="incident-description"
                rows={5}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Describe what occurred, who was present, any damage or disruption, and any immediate actions taken..."
                aria-invalid={!!errors.description}
                aria-describedby={errors.description ? 'description-error' : undefined}
                className={`w-full px-3.5 py-2.5 text-sm rounded-lg border bg-white focus:outline-none focus:ring-2 ${
                  errors.description
                    ? 'border-rose-400 focus:ring-rose-200'
                    : 'border-slate-300 focus:border-indigo-600 focus:ring-indigo-100'
                }`}
              />
              {errors.description && (
                <p id="description-error" className="mt-1 text-xs text-rose-600" role="alert">
                  {errors.description}
                </p>
              )}
            </div>

            {/* Location & Occurred At Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label htmlFor="incident-location" className="block text-sm font-semibold text-slate-800 mb-1">
                  Physical Location <span className="text-rose-500">*</span>
                </label>
                <input
                  id="incident-location"
                  type="text"
                  value={location}
                  onChange={(e) => setLocation(e.target.value)}
                  placeholder="e.g., Sciences Complex Hall 3B, Room 102"
                  aria-invalid={!!errors.location}
                  aria-describedby={errors.location ? 'location-error' : undefined}
                  className={`w-full px-3.5 py-2.5 text-sm rounded-lg border bg-white focus:outline-none focus:ring-2 ${
                    errors.location
                      ? 'border-rose-400 focus:ring-rose-200'
                      : 'border-slate-300 focus:border-indigo-600 focus:ring-indigo-100'
                  }`}
                />
                {errors.location && (
                  <p id="location-error" className="mt-1 text-xs text-rose-600" role="alert">
                    {errors.location}
                  </p>
                )}
              </div>

              <div>
                <label htmlFor="incident-occurred-at" className="block text-sm font-semibold text-slate-800 mb-1">
                  Date & Time of Occurrence <span className="text-rose-500">*</span>
                </label>
                <input
                  id="incident-occurred-at"
                  type="datetime-local"
                  value={occurredAt}
                  onChange={(e) => setOccurredAt(e.target.value)}
                  aria-invalid={!!errors.occurredAt}
                  aria-describedby={errors.occurredAt ? 'occurred-error' : undefined}
                  className={`w-full px-3.5 py-2.5 text-sm rounded-lg border bg-white focus:outline-none focus:ring-2 ${
                    errors.occurredAt
                      ? 'border-rose-400 focus:ring-rose-200'
                      : 'border-slate-300 focus:border-indigo-600 focus:ring-indigo-100'
                  }`}
                />
                {errors.occurredAt ? (
                  <p id="occurred-error" className="mt-1 text-xs text-rose-600" role="alert">
                    {errors.occurredAt}
                  </p>
                ) : (
                  <span className="text-xs text-slate-400 mt-1 block">Must not be in the future.</span>
                )}
              </div>
            </div>
          </CardContent>

          <CardFooter className="flex justify-between">
            <Button
              variant="outline"
              onClick={handleBack}
              leftIcon={<ArrowLeft className="h-4 w-4" />}
            >
              Back to Classification
            </Button>
            <Button
              variant="primary"
              onClick={handleNextFromStep2}
              rightIcon={<ArrowRight className="h-4 w-4" />}
            >
              Review & Disclosures
            </Button>
          </CardFooter>
        </Card>
      )}

      {/* STEP 3: REVIEW & IDENTITY DISCLOSURES */}
      {step === 3 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Review Submission & Institutional Disclosures</CardTitle>
                <CardDescription>
                  Review the report contents prior to final submission. Submissions are bound to your verified identity.
                </CardDescription>
              </div>
              <Badge variant="primary">Step 3 of 3</Badge>
            </div>
          </CardHeader>

          <CardContent className="space-y-6">
            {submitError && (
              <Alert variant="error" title="Submission Failed">
                {submitError}
              </Alert>
            )}

            {/* Institutional Identity Notice & Anonymous Policy Card */}
            <div className="p-4 bg-slate-50 border border-slate-200 rounded-lg space-y-3">
              <div className="flex items-start space-x-3">
                <Lock className="h-5 w-5 text-indigo-600 shrink-0 mt-0.5" />
                <div className="text-xs text-slate-600 leading-relaxed">
                  <div className="font-semibold text-slate-900 text-sm mb-0.5">
                    Evidentiary Chain-of-Custody & Accountability Notice
                  </div>
                  <p className="mb-2">
                    In compliance with E-WITNESS evidentiary integrity standards, this submission is authenticated and bound to your institutional account{' '}
                    <strong className="text-slate-800">({user?.email || 'Authenticated User'})</strong>.
                  </p>
                  <p>
                    <strong className="text-slate-800">Anonymous Reporting Policy:</strong> Under university regulations and evidentiary chain-of-custody rules, completely unauthenticated or anonymous reporting is currently <span className="font-semibold text-rose-700">not supported</span> to prevent fraudulent reporting and maintain legal admissibility. However, your identity is kept strictly confidential within the authorized department review team.
                  </p>
                </div>
              </div>
            </div>

            {/* Submission Summary Table */}
            <div className="border border-slate-200 rounded-lg overflow-hidden bg-white">
              <div className="bg-slate-50 px-4 py-3 border-b border-slate-200 text-xs font-semibold text-slate-700 uppercase tracking-wider">
                Submission Summary Preview
              </div>
              <dl className="divide-y divide-slate-100 text-sm">
                <div className="px-4 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                  <dt className="font-medium text-slate-500">Category</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2 flex items-center space-x-2">
                    <span className="font-semibold text-slate-800">{selectedCategoryObj?.label}</span>
                    <Badge variant="default" size="sm">{category}</Badge>
                  </dd>
                </div>
                <div className="px-4 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                  <dt className="font-medium text-slate-500">Severity</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2">
                    <Badge variant={selectedSeverityObj?.badgeVariant || 'default'}>
                      {severity.toUpperCase()}
                    </Badge>
                  </dd>
                </div>
                <div className="px-4 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                  <dt className="font-medium text-slate-500">Title</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2 font-medium text-slate-900">{title}</dd>
                </div>
                <div className="px-4 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                  <dt className="font-medium text-slate-500">Physical Location</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2 text-slate-700">{location}</dd>
                </div>
                <div className="px-4 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                  <dt className="font-medium text-slate-500">Occurred At</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2 text-slate-700">
                    {occurredAt ? new Date(occurredAt).toLocaleString() : 'N/A'}
                  </dd>
                </div>
                <div className="px-4 py-3 sm:grid sm:grid-cols-3 sm:gap-4">
                  <dt className="font-medium text-slate-500">Narrative</dt>
                  <dd className="mt-1 sm:mt-0 sm:col-span-2 text-slate-700 whitespace-pre-wrap leading-relaxed text-xs">
                    {description}
                  </dd>
                </div>
              </dl>
            </div>
          </CardContent>

          <CardFooter className="flex justify-between">
            <Button
              variant="outline"
              onClick={handleBack}
              disabled={isSubmitting}
              leftIcon={<ArrowLeft className="h-4 w-4" />}
            >
              Back to Details
            </Button>
            <Button
              variant="primary"
              onClick={handleSubmit}
              isLoading={isSubmitting}
              leftIcon={<CheckCircle2 className="h-4 w-4" />}
            >
              Confirm & Submit Report
            </Button>
          </CardFooter>
        </Card>
      )}

      {/* STEP 4: SUBMISSION CONFIRMATION */}
      {step === 4 && createdIncident && (
        <Card className="border-emerald-200 bg-white">
          <CardContent className="pt-8 pb-8 text-center space-y-6">
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
              <CheckCircle2 className="h-8 w-8" />
            </div>

            <div className="space-y-2">
              <h2 className="text-xl font-bold text-slate-900">Incident Report Submitted Successfully</h2>
              <p className="text-sm text-slate-600 max-w-lg mx-auto">
                Your incident report has been registered into the E-WITNESS system and assigned a tamper-evident reference identifier.
              </p>
            </div>

            {/* Reference Number Box */}
            <div className="max-w-md mx-auto p-4 bg-slate-50 border border-slate-200 rounded-lg flex items-center justify-between">
              <div className="text-left">
                <span className="block text-xs uppercase font-semibold text-slate-400">Reference Number</span>
                <span className="text-lg font-mono font-bold text-indigo-700">
                  {createdIncident.reference_number}
                </span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCopyRef}
                leftIcon={copiedRef ? <Check className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}
              >
                {copiedRef ? 'Copied' : 'Copy'}
              </Button>
            </div>

            {/* Next Steps Guidance */}
            <div className="max-w-lg mx-auto text-left p-4 bg-blue-50/60 border border-blue-100 rounded-lg text-xs text-blue-900 space-y-1.5">
              <div className="font-semibold text-blue-950 flex items-center space-x-1.5">
                <Info className="h-4 w-4 text-blue-600" />
                <span>What Happens Next?</span>
              </div>
              <ul className="list-disc list-inside space-y-1 text-slate-600 pl-1">
                <li>Your report is queued in the department triage workspace (`SUBMITTED`).</li>
                <li>An authorized departmental reviewer will assess severity and triage the report.</li>
                <li>You can monitor the status of this report using the reference number.</li>
              </ul>
            </div>

            {/* Action Buttons */}
            <div className="pt-4 flex flex-wrap justify-center gap-3">
              <Button
                variant="outline"
                onClick={handleReset}
                leftIcon={<RotateCcw className="h-4 w-4" />}
              >
                Report Another Incident
              </Button>
              {onViewMyReports && (
                <Button
                  variant="primary"
                  onClick={onViewMyReports}
                  rightIcon={<ArrowRight className="h-4 w-4" />}
                >
                  View My Submissions
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
};
