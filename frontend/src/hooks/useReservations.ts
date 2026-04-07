import { useState, useEffect, useCallback } from 'react';
import type { Reservation } from '../types';
import { getReservations } from '../api/client';
import { formatDate } from '../utils/timeUtils';

export function useReservations(startDate: Date, endDate: Date) {
  const [reservations, setReservations] = useState<Reservation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchReservations = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getReservations({
        start_date: formatDate(startDate),
        end_date: formatDate(endDate),
      });
      setReservations(res.data ?? []);
    } catch (err) {
      setError('予約データの取得に失敗しました');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [startDate, endDate]);

  useEffect(() => {
    fetchReservations();
  }, [fetchReservations]);

  return { reservations, loading, error, refetch: fetchReservations };
}
