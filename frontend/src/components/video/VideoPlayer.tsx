import React, { useState, useRef, useEffect, useCallback } from 'react';
import {
  Play,
  Pause,
  RotateCcw,
  RotateCw,
  Volume2,
  VolumeX,
  Maximize2,
  RefreshCw,
  AlertTriangle,
  Clock,
  Film,
} from 'lucide-react';
import { Button } from '../ui/Button';
import type { CaseAISegmentRead } from '../../types/case';
import { formatTime } from './video.utils';

interface VideoPlayerProps {
  src: string | null;
  filename: string;
  contentType?: string;
  isLoadingUrl?: boolean;
  urlExpiresAt?: string | null;
  onRefreshUrl?: () => void;
  segments?: CaseAISegmentRead[];
  activeSegmentId?: string | null;
  onSelectSegment?: (segment: CaseAISegmentRead) => void;
  onTimeUpdate?: (currentTime: number) => void;
  videoRefCallback?: (element: HTMLVideoElement | null) => void;
}

export const VideoPlayer: React.FC<VideoPlayerProps> = ({
  src,
  filename,
  contentType,
  isLoadingUrl = false,
  urlExpiresAt,
  onRefreshUrl,
  segments = [],
  onSelectSegment,
  onTimeUpdate,
  videoRefCallback,
}) => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [duration, setDuration] = useState<number>(0);
  const [volume, setVolume] = useState<number>(1.0);
  const [isMuted, setIsMuted] = useState<boolean>(false);
  const [playbackRate, setPlaybackRate] = useState<number>(1.0);
  const [hasPlaybackError, setHasPlaybackError] = useState<boolean>(false);
  const [isUrlExpired, setIsUrlExpired] = useState<boolean>(false);

  // Check URL expiration
  useEffect(() => {
    if (!urlExpiresAt) return;

    const checkExpiration = () => {
      const expirationDate = new Date(urlExpiresAt).getTime();
      const now = Date.now();
      if (now >= expirationDate) {
        setIsUrlExpired(true);
      } else {
        setIsUrlExpired(false);
      }
    };

    checkExpiration();
    const interval = setInterval(checkExpiration, 10000);
    return () => clearInterval(interval);
  }, [urlExpiresAt]);

  // Pass ref callback upwards if provided
  useEffect(() => {
    if (videoRefCallback) {
      videoRefCallback(videoRef.current);
    }
  }, [videoRefCallback]);

  // Handle play/pause
  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;

    if (video.paused || video.ended) {
      video.play().catch(() => {
        setHasPlaybackError(true);
      });
    } else {
      video.pause();
    }
  }, []);

  // Handle seeking
  const handleSeek = useCallback(
    (newTime: number) => {
      const video = videoRef.current;
      if (!video) return;
      const clampedTime = Math.max(0, Math.min(newTime, duration || 0));
      video.currentTime = clampedTime;
      setCurrentTime(clampedTime);
      if (onTimeUpdate) {
        onTimeUpdate(clampedTime);
      }
    },
    [duration, onTimeUpdate]
  );

  const handleSkip = useCallback(
    (deltaSeconds: number) => {
      if (!videoRef.current) return;
      handleSeek(currentTime + deltaSeconds);
    },
    [currentTime, handleSeek]
  );

  // Handle volume & mute
  const handleVolumeChange = useCallback(
    (newVolume: number) => {
      const video = videoRef.current;
      if (!video) return;
      const clamped = Math.max(0, Math.min(newVolume, 1));
      video.volume = clamped;
      setVolume(clamped);
      if (clamped === 0) {
        video.muted = true;
        setIsMuted(true);
      } else if (isMuted) {
        video.muted = false;
        setIsMuted(false);
      }
    },
    [isMuted]
  );

  const toggleMute = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    video.muted = !isMuted;
    setIsMuted(!isMuted);
  }, [isMuted]);

  // Handle playback rate
  const handleRateChange = (rate: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.playbackRate = rate;
    setPlaybackRate(rate);
  };

  // Handle fullscreen
  const toggleFullscreen = useCallback(() => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch(() => {});
    } else {
      document.exitFullscreen().catch(() => {});
    }
  }, []);

  // Keyboard shortcut controls
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      // Don't intercept if focus is inside an input, textarea, or select
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes((e.target as HTMLElement).tagName)) {
        return;
      }

      switch (e.key) {
        case ' ':
        case 'k':
          e.preventDefault();
          togglePlay();
          break;
        case 'ArrowLeft':
          e.preventDefault();
          handleSkip(-5);
          break;
        case 'ArrowRight':
          e.preventDefault();
          handleSkip(5);
          break;
        case 'j':
          e.preventDefault();
          handleSkip(-10);
          break;
        case 'l':
          e.preventDefault();
          handleSkip(10);
          break;
        case 'ArrowUp':
          e.preventDefault();
          handleVolumeChange(volume + 0.1);
          break;
        case 'ArrowDown':
          e.preventDefault();
          handleVolumeChange(volume - 0.1);
          break;
        case 'm':
          e.preventDefault();
          toggleMute();
          break;
        case 'f':
          e.preventDefault();
          toggleFullscreen();
          break;
        default:
          break;
      }
    },
    [togglePlay, handleSkip, handleVolumeChange, volume, toggleMute, toggleFullscreen]
  );

  // Video event handlers
  const onTimeUpdateHandler = () => {
    const video = videoRef.current;
    if (!video) return;
    setCurrentTime(video.currentTime);
    if (onTimeUpdate) {
      onTimeUpdate(video.currentTime);
    }
  };

  const onLoadedMetadataHandler = () => {
    const video = videoRef.current;
    if (!video) return;
    setDuration(video.duration);
    setHasPlaybackError(false);
  };

  const isVideoFormat =
    !contentType ||
    contentType.startsWith('video/') ||
    filename.match(/\.(mp4|webm|mov|avi)$/i);

  if (!isVideoFormat) {
    return (
      <div className="p-8 text-center bg-slate-900 rounded-xl border border-slate-800 text-slate-300 space-y-3">
        <Film className="h-10 w-10 text-slate-500 mx-auto" />
        <h4 className="text-base font-semibold text-slate-200">Non-Video Evidence File</h4>
        <p className="text-xs text-slate-400 max-w-md mx-auto">
          The selected evidence attachment ({filename}) has MIME type{' '}
          <code className="text-amber-300 font-mono">{contentType || 'unknown'}</code>, which is
          not a browser-playable video format.
        </p>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      tabIndex={0}
      role="region"
      aria-label={`Video Evidence Player: ${filename}`}
      onKeyDown={handleKeyDown}
      className="relative flex flex-col bg-slate-950 rounded-xl overflow-hidden border border-slate-800 shadow-xl focus:outline-none focus:ring-2 focus:ring-indigo-500"
    >
      {/* Video Canvas Container */}
      <div className="relative aspect-video w-full bg-black flex items-center justify-center overflow-hidden">
        {/* Loading state */}
        {isLoadingUrl && (
          <div className="absolute inset-0 z-30 bg-slate-950/80 flex flex-col items-center justify-center gap-3">
            <RefreshCw className="h-8 w-8 text-indigo-400 animate-spin" />
            <p className="text-xs text-slate-300 font-medium">Requesting authorized streaming URL…</p>
          </div>
        )}

        {/* Expired URL overlay */}
        {isUrlExpired && !isLoadingUrl && (
          <div className="absolute inset-0 z-30 bg-slate-950/90 flex flex-col items-center justify-center p-6 text-center gap-3">
            <Clock className="h-10 w-10 text-amber-400" />
            <h5 className="text-sm font-semibold text-slate-200">Presigned Access URL Expired</h5>
            <p className="text-xs text-slate-400 max-w-sm">
              The temporary download token for this video evidence has expired in accordance with institutional security policy.
            </p>
            {onRefreshUrl && (
              <Button variant="primary" size="sm" onClick={onRefreshUrl}>
                <RefreshCw className="h-4 w-4 mr-1.5" />
                Refresh Access Token
              </Button>
            )}
          </div>
        )}

        {/* Playback error overlay */}
        {hasPlaybackError && !isLoadingUrl && !isUrlExpired && (
          <div className="absolute inset-0 z-30 bg-slate-950/90 flex flex-col items-center justify-center p-6 text-center gap-3">
            <AlertTriangle className="h-10 w-10 text-rose-500" />
            <h5 className="text-sm font-semibold text-slate-200">Video Playback Error</h5>
            <p className="text-xs text-slate-400 max-w-sm">
              The browser was unable to decode the video stream or authorization was refused.
            </p>
            {onRefreshUrl && (
              <Button variant="outline" size="sm" onClick={onRefreshUrl} className="text-slate-200 border-slate-700">
                <RefreshCw className="h-4 w-4 mr-1.5" />
                Retry Video Stream
              </Button>
            )}
          </div>
        )}

        {/* The Native HTML5 Video Element */}
        {src ? (
          <video
            ref={videoRef}
            src={src}
            crossOrigin="anonymous"
            playsInline
            onPlay={() => setIsPlaying(true)}
            onPause={() => setIsPlaying(false)}
            onTimeUpdate={onTimeUpdateHandler}
            onLoadedMetadata={onLoadedMetadataHandler}
            onError={() => setHasPlaybackError(true)}
            onClick={togglePlay}
            className="w-full h-full object-contain cursor-pointer"
          />
        ) : (
          !isLoadingUrl && (
            <div className="text-center p-6 text-slate-500 space-y-2">
              <Film className="h-8 w-8 mx-auto text-slate-600" />
              <p className="text-xs">No video stream loaded.</p>
            </div>
          )
        )}
      </div>

      {/* Temporal Candidate Segments Scrubber Track Overlay */}
      {duration > 0 && segments.length > 0 && (
        <div className="relative h-2 w-full bg-slate-900 border-t border-slate-800">
          {segments.map((seg) => {
            const leftPct = Math.max(0, Math.min(100, (seg.start_seconds / duration) * 100));
            const widthPct = Math.max(
              0.5,
              Math.min(100 - leftPct, ((seg.end_seconds - seg.start_seconds) / duration) * 100)
            );

            // Color coding based on review status
            let segColor = 'bg-amber-500/70 hover:bg-amber-400';
            if (seg.review_status === 'confirmed') segColor = 'bg-emerald-500/70 hover:bg-emerald-400';
            else if (seg.review_status === 'rejected') segColor = 'bg-rose-500/70 hover:bg-rose-400';
            else if (seg.review_status === 'inconclusive') segColor = 'bg-slate-500/70 hover:bg-slate-400';
            else if (seg.review_status === 'escalated') segColor = 'bg-purple-500/70 hover:bg-purple-400';

            return (
              <button
                key={seg.id}
                type="button"
                onClick={() => {
                  handleSeek(seg.start_seconds);
                  if (onSelectSegment) onSelectSegment(seg);
                }}
                title={`AI Segment [${formatTime(seg.start_seconds)} - ${formatTime(seg.end_seconds)}]: ${seg.label} (${(seg.score * 100).toFixed(0)}%) - Status: ${seg.review_status}`}
                style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
                className={`absolute top-0 bottom-0 transition-colors cursor-pointer ${segColor}`}
              />
            );
          })}
        </div>
      )}

      {/* Control Bar */}
      <div className="px-4 py-2.5 bg-slate-900 border-t border-slate-800 flex flex-col gap-2">
        {/* Scrubber Range Slider */}
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-mono text-slate-400 min-w-[36px] text-right">
            {formatTime(currentTime)}
          </span>
          <input
            type="range"
            min={0}
            max={duration || 100}
            step={0.1}
            value={currentTime}
            onChange={(e) => handleSeek(parseFloat(e.target.value))}
            aria-label="Video scrubber slider"
            aria-valuemin={0}
            aria-valuemax={duration}
            aria-valuenow={currentTime}
            className="flex-1 h-1.5 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-400"
          />
          <span className="text-[11px] font-mono text-slate-400 min-w-[36px]">
            {formatTime(duration)}
          </span>
        </div>

        {/* Buttons and Settings */}
        <div className="flex items-center justify-between gap-3 text-slate-300">
          {/* Left Controls: Play, Skip, Volume */}
          <div className="flex items-center gap-1.5 sm:gap-2">
            <Button
              variant="ghost"
              size="sm"
              onClick={togglePlay}
              aria-label={isPlaying ? 'Pause video (Space)' : 'Play video (Space)'}
              className="text-slate-200 hover:text-white hover:bg-slate-800 px-2.5 py-1"
            >
              {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleSkip(-5)}
              aria-label="Skip backward 5 seconds (Left Arrow)"
              className="text-slate-400 hover:text-white hover:bg-slate-800 px-2 py-1"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </Button>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleSkip(5)}
              aria-label="Skip forward 5 seconds (Right Arrow)"
              className="text-slate-400 hover:text-white hover:bg-slate-800 px-2 py-1"
            >
              <RotateCw className="h-3.5 w-3.5" />
            </Button>

            {/* Volume */}
            <div className="flex items-center gap-1 ml-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleMute}
                aria-label={isMuted ? 'Unmute (m)' : 'Mute (m)'}
                className="text-slate-400 hover:text-white hover:bg-slate-800 p-1"
              >
                {isMuted || volume === 0 ? (
                  <VolumeX className="h-4 w-4 text-rose-400" />
                ) : (
                  <Volume2 className="h-4 w-4" />
                )}
              </Button>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={isMuted ? 0 : volume}
                onChange={(e) => handleVolumeChange(parseFloat(e.target.value))}
                aria-label="Volume slider"
                className="w-14 sm:w-18 h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />
            </div>
          </div>

          {/* Right Controls: Speed, Fullscreen */}
          <div className="flex items-center gap-2">
            {/* Playback speed selector */}
            <label className="text-[11px] text-slate-400 flex items-center gap-1">
              <span>Speed:</span>
              <select
                value={playbackRate}
                onChange={(e) => handleRateChange(parseFloat(e.target.value))}
                aria-label="Playback speed"
                className="bg-slate-800 text-slate-200 border border-slate-700 rounded px-1.5 py-0.5 text-xs focus:outline-none focus:ring-1 focus:ring-indigo-400"
              >
                <option value={0.5}>0.5x</option>
                <option value={1.0}>1.0x</option>
                <option value={1.25}>1.25x</option>
                <option value={1.5}>1.5x</option>
                <option value={2.0}>2.0x</option>
              </select>
            </label>

            {/* Fullscreen Button */}
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleFullscreen}
              aria-label="Toggle fullscreen (f)"
              className="text-slate-400 hover:text-white hover:bg-slate-800 p-1.5"
            >
              <Maximize2 className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
