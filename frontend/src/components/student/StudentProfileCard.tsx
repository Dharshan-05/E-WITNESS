import React from 'react';
import {
  GraduationCap,
  ShieldCheck,
  Building,
  Mail,
  Fingerprint,
  Calendar,
  Lock,
  Video,
  FileText,
} from 'lucide-react';
import { Card, CardContent } from '../ui/Card';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { useAuth } from '../../auth';

interface StudentProfileCardProps {
  onReportIncident?: () => void;
  onViewMySubmissions?: () => void;
}

export const StudentProfileCard: React.FC<StudentProfileCardProps> = ({
  onReportIncident,
  onViewMySubmissions,
}) => {
  const { user, role, department } = useAuth();

  if (!user) return null;

  const studentId = user.institutional_id || `STU-${user.id.slice(0, 8).toUpperCase()}`;
  const departmentName = department?.name || 'General Student Body';
  const departmentCode = department?.code || 'ACAD';

  return (
    <Card className="border-indigo-100 bg-gradient-to-r from-indigo-50/50 via-white to-slate-50/60 shadow-sm overflow-hidden">
      <CardContent className="p-5 sm:p-6">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          {/* Student Identity Section */}
          <div className="flex items-start gap-4">
            <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-indigo-600 text-white shadow-md ring-4 ring-indigo-50">
              <GraduationCap className="h-8 w-8" />
            </div>

            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-xl font-bold tracking-tight text-slate-900">
                  {user.full_name || 'Enrolled Student'}
                </h2>
                <Badge variant="primary" size="sm" className="font-semibold">
                  {role?.name || 'Student'}
                </Badge>
                <Badge variant="success" size="sm" className="flex items-center gap-1 font-medium">
                  <ShieldCheck className="h-3 w-3" />
                  <span>Active & Verified</span>
                </Badge>
              </div>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600 pt-0.5">
                <div className="flex items-center gap-1.5">
                  <Fingerprint className="h-3.5 w-3.5 text-indigo-500" />
                  <span className="font-medium text-slate-500">Student ID:</span>
                  <span className="font-mono font-bold text-slate-800">{studentId}</span>
                </div>

                <div className="flex items-center gap-1.5">
                  <Mail className="h-3.5 w-3.5 text-slate-400" />
                  <span className="font-mono text-slate-700">{user.email}</span>
                </div>

                <div className="flex items-center gap-1.5">
                  <Building className="h-3.5 w-3.5 text-amber-500" />
                  <span className="font-medium text-slate-500">Department:</span>
                  <span className="text-slate-800 font-medium">
                    {departmentName} ({departmentCode})
                  </span>
                </div>
              </div>

              <div className="flex items-center gap-2 text-[11px] text-slate-400 pt-1">
                <Lock className="h-3 w-3 text-emerald-500" />
                <span>Session Terminal Authenticated:</span>
                <span className="font-mono text-slate-500">
                  {user.session_id ? `${user.session_id.slice(0, 8)}...` : 'Active'}
                </span>
                <span>•</span>
                <Calendar className="h-3 w-3 text-slate-400" />
                <span>Enrolled since: {new Date(user.created_at).toLocaleDateString()}</span>
              </div>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="flex flex-wrap sm:flex-nowrap items-center gap-2.5 shrink-0">
            {onReportIncident && (
              <Button
                variant="primary"
                size="sm"
                onClick={onReportIncident}
                leftIcon={<Video className="h-4 w-4" />}
                className="shadow-sm"
              >
                Record Video Incident
              </Button>
            )}
            {onViewMySubmissions && (
              <Button
                variant="outline"
                size="sm"
                onClick={onViewMySubmissions}
                leftIcon={<FileText className="h-4 w-4" />}
              >
                My Submissions
              </Button>
            )}
          </div>
        </div>

        {/* Security / Evidence Custody Banner */}
        <div className="mt-4 pt-3.5 border-t border-slate-200/70 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-xs text-slate-600 bg-indigo-50/40 -mx-5 -mb-5 px-5 py-2.5 rounded-b-xl">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-indigo-600 shrink-0" />
            <span className="font-medium">
              Student Custody Standard: All incident submissions enforce live video recording with automated geolocation and hardware timestamp attestation. Manual file uploads from local disk are disabled for student protection.
            </span>
          </div>
          <span className="text-[10px] uppercase font-mono font-bold text-indigo-600 bg-white px-2 py-0.5 rounded border border-indigo-200 shrink-0">
            Tamper-Evident Chain
          </span>
        </div>
      </CardContent>
    </Card>
  );
};

