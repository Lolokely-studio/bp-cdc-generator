"use client";

import { useParams } from "next/navigation";
import { ExportsView } from "@/components/ExportsView";

export default function ExportsPage() {
  const { id } = useParams<{ id: string }>();
  return <ExportsView projectId={id} />;
}
