import { useMarketHours } from "@/hooks/use-market-data";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Loader2, Clock } from "lucide-react";
import { format } from "date-fns";

export default function MarketHours() {
  const { data, isLoading, error, isError } = useMarketHours();
  
  if (isLoading) {
    return (
      <Card className="w-full border-[#00b4d8]/20 bg-black/5">
        <CardHeader>
          <CardTitle className="flex items-center text-[#00b4d8]">
            <Clock className="mr-2 h-5 w-5" />
            Market Hours
          </CardTitle>
          <CardDescription>Status of major trading markets</CardDescription>
        </CardHeader>
        <CardContent className="flex justify-center py-6">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }
  
  if (isError) {
    return (
      <Card className="w-full border-[#00b4d8]/20 bg-black/5">
        <CardHeader>
          <CardTitle className="flex items-center text-[#00b4d8]">
            <Clock className="mr-2 h-5 w-5" />
            Market Hours
          </CardTitle>
          <CardDescription>Status of major trading markets</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-center p-4 text-destructive">
            Error loading market data: {error.message}
          </div>
        </CardContent>
      </Card>
    );
  }
  
  // If data is not available, show a fallback
  if (!data) {
    return (
      <Card className="w-full border-[#00b4d8]/20 bg-black/5">
        <CardHeader>
          <CardTitle className="flex items-center text-[#00b4d8]">
            <Clock className="mr-2 h-5 w-5" />
            Market Hours
          </CardTitle>
          <CardDescription>Status of major trading markets</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-center p-4 text-muted-foreground">
            No market data available at the moment.
          </div>
        </CardContent>
      </Card>
    );
  }

  // Format the timestamp to display
  const timeString = new Date(data.timestamp * 1000).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true
  });
  
  const dateString = format(new Date(data.timestamp * 1000), 'EEEE, MMMM d, yyyy');
  
  return (
    <Card className="w-full border-[#00b4d8]/20 bg-black/5">
      <CardHeader>
        <CardTitle className="flex items-center text-[#00b4d8]">
          <Clock className="mr-2 h-5 w-5" />
          Market Hours
        </CardTitle>
        <CardDescription className="flex flex-col sm:flex-row sm:justify-between">
          <span>Status of major trading markets</span>
          <span className="text-sm font-medium mt-1 sm:mt-0">
            {dateString} at {timeString}
          </span>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {data.markets.map((market, index) => (
            <div key={market.abbreviation}>
              <div className="flex justify-between items-center">
                <div>
                  <h4 className="font-medium text-sm">{market.name}</h4>
                  <p className="text-xs text-muted-foreground">{market.currentTime} - {market.timeZone}</p>
                </div>
                <Badge 
                  variant={market.status === 'open' ? 'default' : 'secondary'}
                  className={
                    market.status === 'open' 
                      ? 'bg-green-500 hover:bg-green-600' 
                      : 'bg-gray-500 hover:bg-gray-600'
                  }
                >
                  {market.status === 'open' ? 'OPEN' : 'CLOSED'}
                </Badge>
              </div>
              <div className="text-xs text-muted-foreground mt-1">
                Trading hours: {market.openTime} - {market.closeTime} 
                {market.abbreviation === 'CRYPTO' && ' (24/7)'}
              </div>
              
              {index < data.markets.length - 1 && (
                <Separator className="my-3" />
              )}
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}