"use client";

import useSWR from "swr";
import { fetchIncidents, type Incident } from "@/lib/api";

/**
 * Fetch incidents with SWR auto-revalidation.
 * Polls every `refreshInterval` ms (default 5 s).
 */
export function useIncidents(refreshInterval = 5_000) {
  const { data, error, isLoading, mutate } = useSWR(
    "incidents",
    () => fetchIncidents(28.6139, 77.209, 50_000, 100),
    {
      refreshInterval,
      revalidateOnFocus: true,
      errorRetryCount: 3,
      dedupingInterval: 2_000,
    },
  );

  return {
    incidents: data?.incidents ?? ([] as Incident[]),
    count: data?.count ?? 0,
    isLoading,
    error,
    refresh: mutate,
  };
}
