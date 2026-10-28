import React from 'react';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';

export interface SkeletonProps extends React.HTMLAttributes<HTMLDivElement> {
  width?: string | number;
  height?: string | number;
  circle?: boolean;
}

export const Skeleton: React.FC<SkeletonProps> = ({
  className,
  width,
  height,
  circle = false,
  style,
  ...props
}) => {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      className={twMerge(
        clsx(
          'animate-pulse bg-slate-200',
          circle ? 'rounded-full' : 'rounded-md',
          className
        )
      )}
      style={{
        width: typeof width === 'number' ? `${width}px` : width,
        height: typeof height === 'number' ? `${height}px` : height,
        ...style,
      }}
      {...props}
    />
  );
};
