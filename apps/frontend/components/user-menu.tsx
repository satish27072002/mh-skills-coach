"use client";

import { LogOut, UserCircle2 } from "lucide-react";
import { useRouter } from "next/navigation";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "./ui/dropdown-menu";
import { Button } from "./ui/button";

export default function UserMenu({
  isAuthenticated,
  isPremium,
  isGuest,
  onUpgrade
}: {
  isAuthenticated: boolean;
  isPremium: boolean;
  isGuest?: boolean;
  onUpgrade: () => void;
}) {
  const router = useRouter();

  const handleLogout = async () => {
    try {
      await fetch("/api/logout", { method: "POST", credentials: "include", cache: "no-store" });
    } finally {
      router.replace("/login");
    }
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="icon" aria-label="Open account menu">
          <UserCircle2 className="h-5 w-5" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>{isGuest ? "Guest session" : isPremium ? "Premium account" : "Free account"}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {isGuest ? (
          <DropdownMenuItem onClick={() => router.push("/login")}>
            Sign in with Google
          </DropdownMenuItem>
        ) : null}
        {!isPremium && isAuthenticated ? <DropdownMenuItem onClick={onUpgrade}>Upgrade to premium</DropdownMenuItem> : null}
        {isAuthenticated ? (
          <DropdownMenuItem onClick={handleLogout} className="text-red-600 dark:text-red-400">
            <LogOut className="mr-2 h-4 w-4" />
            Logout
          </DropdownMenuItem>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
