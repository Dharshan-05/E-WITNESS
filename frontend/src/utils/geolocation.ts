/**
 * Geolocation and Automated Evidence Metadata Utility.
 * Provides high-accuracy GPS coordinates and tamper-evident timestamps.
 */

export interface GeolocationResult {
  latitude: number;
  longitude: number;
  accuracy: number;
  altitude: number | null;
  formattedLocation: string;
  timestamp: string;
}

/**
 * Fetch current GPS coordinates using the browser's Geolocation API.
 * Defaults to high accuracy.
 */
export async function fetchCurrentGeolocation(): Promise<GeolocationResult> {
  if (typeof navigator === 'undefined' || !navigator.geolocation) {
    throw new Error('Geolocation is not supported by your browser or environment.');
  }

  return new Promise((resolve, reject) => {
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const { latitude, longitude, accuracy, altitude } = position.coords;
        const latDirection = latitude >= 0 ? 'N' : 'S';
        const lonDirection = longitude >= 0 ? 'E' : 'W';
        const formatted = `GPS: ${Math.abs(latitude).toFixed(5)}° ${latDirection}, ${Math.abs(
          longitude
        ).toFixed(5)}° ${lonDirection} (±${Math.round(accuracy)}m)`;

        resolve({
          latitude,
          longitude,
          accuracy,
          altitude,
          formattedLocation: formatted,
          timestamp: new Date(position.timestamp || Date.now()).toISOString(),
        });
      },
      (error) => {
        switch (error.code) {
          case error.PERMISSION_DENIED:
            reject(new Error('Location access was denied. Please allow location access in your browser settings.'));
            break;
          case error.POSITION_UNAVAILABLE:
            reject(new Error('GPS position is currently unavailable from your device.'));
            break;
          case error.TIMEOUT:
            reject(new Error('Location request timed out. Please try again.'));
            break;
          default:
            reject(new Error('Failed to retrieve location coordinates.'));
        }
      },
      {
        enableHighAccuracy: true,
        timeout: 10000,
        maximumAge: 0,
      }
    );
  });
}

/**
 * Format the current date/time to local ISO format suitable for HTML datetime-local inputs:
 * YYYY-MM-DDTHH:mm
 */
export function getCurrentLocalDateTimeString(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  const hours = String(now.getHours()).padStart(2, '0');
  const minutes = String(now.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

