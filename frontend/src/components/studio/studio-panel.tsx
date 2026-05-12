"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { AudioPanel } from "./audio-panel";
import { StudiesPanel } from "./studies-panel";
import { NotesPanel } from "./notes-panel";
import { ReportsPanel } from "./reports-panel";

export function StudioPanel({ notebookId }: { notebookId: string }) {
  return (
    <Tabs defaultValue="audio" className="flex h-full flex-col">
      <TabsList className="grid grid-cols-4">
        <TabsTrigger value="audio">Audio</TabsTrigger>
        <TabsTrigger value="studies">Studies</TabsTrigger>
        <TabsTrigger value="notes">Notes</TabsTrigger>
        <TabsTrigger value="reports">Reports</TabsTrigger>
      </TabsList>
      <TabsContent value="audio" className="mt-3 flex-1 overflow-y-auto">
        <AudioPanel notebookId={notebookId} />
      </TabsContent>
      <TabsContent value="studies" className="mt-3 flex-1 overflow-y-auto">
        <StudiesPanel notebookId={notebookId} />
      </TabsContent>
      <TabsContent value="notes" className="mt-3 flex-1 overflow-y-auto">
        <NotesPanel notebookId={notebookId} />
      </TabsContent>
      <TabsContent value="reports" className="mt-3 flex-1 overflow-y-auto">
        <ReportsPanel notebookId={notebookId} />
      </TabsContent>
    </Tabs>
  );
}
