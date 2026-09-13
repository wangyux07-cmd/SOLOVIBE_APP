import React, { useEffect, useRef, useState } from 'react';
// This legacy preview has a different shape from the main application's pins.
interface MapInstancePin {
  id: string;
  name: string;
  lat: number;
  lng: number;
  category: string;
  description: string;
}

interface MapPageProps {
  pins?: MapInstancePin[];
  center?: { lat: number; lng: number };
  zoom?: number;
}

/**
 * 地图页面组件
 * 展示地理位置信息和建议地点
 */
export const MapPage: React.FC<MapPageProps> = ({ 
  pins = [], 
  center = { lat: 31.2304, lng: 121.4737 }, // 上海默认中心
  zoom = 12 
}) => {
  const mapRef = useRef<HTMLDivElement>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const [selectedPin, setSelectedPin] = useState<MapInstancePin | null>(null);

  // 模拟地图数据
  const defaultPins: MapInstancePin[] = [
    {
      id: '1',
      name: '滨江治愈公园',
      lat: 31.2314,
      lng: 121.4747,
      category: '治愈',
      description: '安静的河流沿岸，适合发呆和放松'
    },
    {
      id: '2', 
      name: '艺术街区',
      lat: 31.2294,
      lng: 121.4717,
      category: '探索',
      description: '充满创意气息的小巷子'
    },
    {
      id: '3',
      name: '树林阅读角',
      lat: 31.2284,
      lng: 121.4767,
      category: '阅读',
      description: '被绿树环绕的安静角落'
    }
  ];

  const allPins = pins.length > 0 ? pins : defaultPins;

  useEffect(() => {
    // 这里是地图初始化逻辑
    // 实际项目中会集成高德地图或其他地图服务
    setIsLoaded(true);
  }, []);

  if (!isLoaded) {
    return (
      <div className="w-full h-96 bg-gray-100 rounded-lg flex items-center justify-center">
        <div className="text-gray-500">地图加载中...</div>
      </div>
    );
  }

  return (
    <div className="w-full h-96 bg-gray-100 rounded-lg overflow-hidden">
      {/* 模拟地图显示 */}
      <div 
        ref={mapRef}
        className="w-full h-full relative"
        style={{
          background: 'linear-gradient(135deg, #e5f3ff 0%, #cce7ff 100%)'
        }}
      >
        {/* 地图标记点 */}
        {allPins.map((pin, index) => (
          <div
            key={pin.id}
            className={`absolute w-4 h-4 rounded-full border-2 border-white shadow-lg cursor-pointer transform -translate-x-2 -translate-y-4 hover:scale-125 transition-transform ${
              selectedPin?.id === pin.id ? 'bg-blue-500' : 'bg-green-500'
            }`}
            style={{
              left: `${30 + index * 20}%`,
              top: `${40 + index * 15}%`
            }}
            onClick={() => setSelectedPin(pin)}
          />
        ))}

        {/* 地图信息卡片 */}
        {selectedPin && (
          <div className="absolute bottom-4 left-4 bg-white rounded-lg shadow-lg p-4 max-w-xs">
            <h3 className="font-semibold text-gray-800">{selectedPin.name}</h3>
            <p className="text-sm text-gray-600 mt-1">{selectedPin.description}</p>
            <div className="flex items-center justify-between mt-2">
              <span className="text-xs text-gray-500">
                {selectedPin.category}
              </span>
              <button 
                onClick={() => setSelectedPin(null)}
                className="text-xs text-blue-500 hover:text-blue-700"
              >
                查看详情
              </button>
            </div>
          </div>
        )}

        {/* 地图控制按钮 */}
        <div className="absolute top-4 right-4 space-y-2">
          <button className="w-8 h-8 bg-white rounded shadow text-lg hover:bg-gray-50">
            +
          </button>
          <button className="w-8 h-8 bg-white rounded shadow text-lg hover:bg-gray-50">
            -
          </button>
        </div>
      </div>

      {/* 图例 */}
      <div className="bg-white p-3 border-t">
        <div className="flex items-center space-x-4 text-sm">
          <div className="flex items-center space-x-1">
            <div className="w-3 h-3 rounded-full bg-green-500"></div>
            <span>独处好去处</span>
          </div>
          <div className="flex items-center space-x-1">
            <div className="w-3 h-3 rounded-full bg-blue-500"></div>
            <span>已选择</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MapPage;
