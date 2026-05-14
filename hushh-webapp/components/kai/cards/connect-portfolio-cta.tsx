"use client";

import { ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";

import { SurfaceCard, SurfaceCardContent } from "@/components/app-ui/surfaces";
import { Button } from "@/lib/morphy-ux/button";
import { Icon } from "@/lib/morphy-ux/ui";

export function ConnectPortfolioCta() {
  const router = useRouter();

  return (
    <SurfaceCard accent="emerald">
      <SurfaceCardContent className="space-y-4 p-6 text-center">
        <div className="space-y-2">
          <h3 className="text-lg font-black tracking-tight">
            See insights tailored to your portfolio
          </h3>
          <p className="text-sm text-muted-foreground">
            Unlock personalized analysis and real-time alerts.
          </p>
        </div>

        <Button
          size="lg"
          fullWidth
          onClick={() => router.push("/kai/import")}
          showRipple
        >
          Connect Portfolio
          <Icon icon={ArrowRight} size="md" className="ml-2" />
        </Button>

        <Button
          variant="link"
          effect="fill"
          size="sm"
          fullWidth
          onClick={() => router.push("/kai")}
          showRipple={false}
        >
          Or continue exploring
        </Button>
      </SurfaceCardContent>
    </SurfaceCard>
  );
}
